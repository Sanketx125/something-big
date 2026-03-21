"""
convert_to_onnx.py
==================
Converts best_building.pth → best_building.onnx
Includes a live visual timer and suppresses PyTorch warnings.
"""

import sys
import time
import threading
import warnings
import torch
import importlib.util
import numpy as np
from pathlib import Path

# ── Config — perfectly matched to InferenceConfig ────────────────────────────
EXPECTED_NUM_FEATURES = 66
NUM_POINTS            = 8192
INFERENCE_BATCH_SIZE  = 8
OPSET_VERSION         = 18
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ── Find models folder ────────────────────────────────────────────────────
    script_dir = Path(__file__).parent
    
    # Try common locations
    candidates = [
        script_dir / "models" / "best_building.pth",
        script_dir / "gui" / "models" / "best_building.pth",
        Path.cwd() / "models" / "best_building.pth",
    ]
    
    pth_path = None
    for c in candidates:
        if c.exists():
            pth_path = c
            break
    
    if pth_path is None:
        print("ERROR: best_building.pth not found.")
        sys.exit(1)

    model_py_path = pth_path.parent / "model.py"
    onnx_path     = pth_path.with_suffix('.onnx')

    print("=" * 60)
    print("  PTH  → ONNX Conversion (with Live Timer)")
    print("=" * 60)
    print(f"  Input   : {pth_path}")
    print(f"  model.py: {model_py_path}")
    print(f"  Output  : {onnx_path}\n")

    # ── Validate inputs ───────────────────────────────────────────────────────
    if not model_py_path.exists():
        print(f"ERROR: model.py not found at {model_py_path}")
        sys.exit(1)

    if onnx_path.exists():
        print(f"WARNING: {onnx_path.name} already exists — overwriting.\n")

    # ── Load model architecture ───────────────────────────────────────────────
    print("Step 1/4  Loading model architecture from model.py...")
    spec = importlib.util.spec_from_file_location("pointnet2_model", str(model_py_path))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    PointNet2SSG = mod.PointNet2SSG
    print("          OK")

    # ── Load checkpoint ───────────────────────────────────────────────────────
    print("Step 2/4  Loading checkpoint weights...")
    device = torch.device('cpu')
    ckpt   = torch.load(str(pth_path), map_location=device, weights_only=False)

    num_features = ckpt.get('num_features', EXPECTED_NUM_FEATURES)
    num_classes  = ckpt.get('num_classes', 5)

    print(f"          num_features = {num_features}")
    print(f"          num_classes  = {num_classes}")

    model = PointNet2SSG(num_features=num_features, num_classes=num_classes)
    model.load_state_dict(ckpt['model_state_dict'], strict=True)
    model.eval()
    print("          Weights loaded OK")

    # ── Build dummy inputs ────────────────────────────────────────────────────
    print("Step 3/4  Building dummy inputs and tracing the model...")
    dummy_coords = torch.zeros(INFERENCE_BATCH_SIZE, NUM_POINTS, 3, dtype=torch.float32)
    dummy_feats  = torch.zeros(INFERENCE_BATCH_SIZE, NUM_POINTS, num_features, dtype=torch.float32)

    print(f"          coords shape : {tuple(dummy_coords.shape)}")
    print(f"          features shape: {tuple(dummy_feats.shape)}")

    with torch.no_grad():
        test_out = model(dummy_coords, dummy_feats)
    print(f"          Model forward pass OK → output: {tuple(test_out.shape)}")

    # ── Export (Background Thread with Timer) ─────────────────────────────────
    print(f"Step 4/4  Exporting to ONNX (opset {OPSET_VERSION})...")
    
    export_error = None
    export_done = False
    
    def export_task():
        nonlocal export_error, export_done
        try:
            # Catch and ignore all PyTorch internal warnings so they don't ruin the console
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with torch.no_grad():
                    torch.onnx.export(
                        model,
                        (dummy_coords, dummy_feats),
                        str(onnx_path),
                        export_params       = True,
                        opset_version       = OPSET_VERSION,
                        do_constant_folding = True,
                        input_names         = ['coords', 'features'],
                        output_names        = ['logits'],
                        dynamic_axes        = {
                            'coords':   {0: 'batch'},
                            'features': {0: 'batch'},
                            'logits':   {0: 'batch'},
                        },
                        verbose=False,
                    )
        except Exception as e:
            export_error = e
        finally:
            export_done = True

    # Start the export in a background thread
    export_thread = threading.Thread(target=export_task)
    export_thread.start()

    # While the thread runs, show a spinning timer in the main console
    start_time = time.time()
    spinner = ['|', '/', '-', '\\']
    spin_idx = 0
    
    try:
        while not export_done:
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r          [ {spinner[spin_idx % 4]} ] Crunching math... Time elapsed: {elapsed:.1f}s ")
            sys.stdout.flush()
            spin_idx += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n          [ X ] Cancelled by user.")
        sys.exit(1)

    export_thread.join()

    if export_error:
        print(f"\r          [ X ] Export FAILED after {time.time() - start_time:.1f}s           ")
        print(f"\nError details: {export_error}")
        sys.exit(1)
    else:
        size_mb = onnx_path.stat().st_size / 1e6
        print(f"\r          [ ✓ ] Export FINISHED in {time.time() - start_time:.1f}s               ")
        print(f"          File size: {size_mb:.1f} MB\n")

    # ── Optional: verify with onnxruntime ─────────────────────────────────────
    try:
        import onnxruntime as ort
        print("Verifying ONNX model with onnxruntime...")
        sess = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
        ort_inputs = {
            'coords':   dummy_coords.numpy(),
            'features': dummy_feats.numpy(),
        }
        ort_out = sess.run(None, ort_inputs)[0]
        print(f"  onnxruntime output shape: {ort_out.shape}  ✓")

        print("=" * 60)
        print("  CONVERSION SUCCESSFUL!")
        print("=" * 60)
        print("  NEXT STEPS:")
        print("  1. The .onnx file is ready in the models folder.")
        print("  2. Start your app — inference.py will automatically detect it.")
        print("  3. Check the log for 'Inference backend: ONNX Runtime'")

    except ImportError:
        print("=" * 60)
        print("  CONVERSION SUCCESSFUL!")
        print("=" * 60)
        print("  (onnxruntime not installed to verify locally, but file is ready)")


if __name__ == "__main__":
    main()