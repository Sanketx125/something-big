import sys
sys.path.insert(0, r's:\SoftWare\Software bunddle\gui\cpp_accel')
import classify_accel
funcs = [m for m in dir(classify_accel) if not m.startswith('_')]
print(f'Total functions: {len(funcs)}')
for f in funcs:
    print(f'  {f}')
