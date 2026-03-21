# ============================================================================
# FILE: vector_export.py
# Complete vector drawing export/import system for NakshaAI-Lidar
# Supports DXF, GeoJSON, and Shapefile formats with full metadata
# ============================================================================

import os
import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PySide6.QtWidgets import QMessageBox, QFileDialog


def diagnose_app_data(app):
    """Debug helper to find where data is stored in the app"""
    print(f"\n{'='*60}")
    print(f"🔍 DIAGNOSING APP DATA STRUCTURE")
    print(f"{'='*60}")
    
    # Check all attributes
    print(f"\n📋 App attributes:")
    for attr in dir(app):
        if not attr.startswith('_'):
            try:
                val = getattr(app, attr)
                if hasattr(val, '__len__') and not isinstance(val, str):
                    print(f"   • {attr}: {type(val).__name__} (length: {len(val)})")
                elif not callable(val):
                    print(f"   • {attr}: {type(val).__name__}")
            except:
                pass
    
    # Check for point cloud specifically
    print(f"\n☁️ Point Cloud Search:")
    for attr in ['point_cloud', 'points', 'cloud', 'pc', 'vtk_points', 'actor']:
        if hasattr(app, attr):
            val = getattr(app, attr)
            print(f"   ✅ Found app.{attr}: {type(val)}")
            if hasattr(val, 'GetNumberOfPoints'):
                print(f"      → VTK object with {val.GetNumberOfPoints()} points")
            elif hasattr(val, '__len__'):
                print(f"      → Length: {len(val)}")
    
    # Check for drawings specifically
    print(f"\n✏️ Drawings Search:")
    if hasattr(app, 'digitizer'):
        print(f"   ✅ app.digitizer exists: {type(app.digitizer)}")
        if hasattr(app.digitizer, 'drawings'):
            print(f"   ✅ app.digitizer.drawings exists: {type(app.digitizer.drawings)}")
            print(f"      → Length: {len(app.digitizer.drawings) if app.digitizer.drawings else 0}")
            if app.digitizer.drawings:
                print(f"      → First drawing: {app.digitizer.drawings[0]}")
        
        # Check other possible attributes
        for attr in dir(app.digitizer):
            if 'draw' in attr.lower() and not attr.startswith('_'):
                val = getattr(app.digitizer, attr, None)
                if val is not None and not callable(val):
                    print(f"   • digitizer.{attr}: {type(val)}")
    else:
        print(f"   ❌ app.digitizer does not exist")
    
    print(f"{'='*60}\n")

# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

def export_drawings_to_shapefile(app, output_path: str) -> bool:
    """
    Export drawings to Shapefile format (ArcGIS/QGIS compatible).
    Creates separate shapefiles for points, lines, and polygons.
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point, LineString, Polygon
        import pandas as pd
        
        print(f"\n{'='*60}")
        print(f"📤 EXPORTING DRAWINGS TO SHAPEFILE")
        print(f"   Path: {output_path}")
        
        # Validate digitizer
        if not hasattr(app, 'digitizer') or not app.digitizer:
            print("   ⚠️ No digitizer found")
            return False
        
        drawings = app.digitizer.drawings
        if not drawings:
            print("   ⚠️ No drawings to export")
            return False
        
        print(f"   📊 Processing {len(drawings)} drawing(s)...")
        
        # ============================================================
        # DIAGNOSTIC: Print full drawing data
        # ============================================================
        print(f"\n   🔍 FULL DRAWING DATA:")
        for idx, drawing in enumerate(drawings):
            print(f"\n   Drawing {idx+1}:")
            for key, value in drawing.items():
                if key == 'coordinates':
                    print(f"      {key}: {len(value) if isinstance(value, list) else 'N/A'} items")
                    if isinstance(value, list) and len(value) > 0:
                        print(f"         First coord: {value[0]}")
                        if len(value) > 1:
                            print(f"         Last coord: {value[-1]}")
                else:
                    print(f"      {key}: {value}")
        
        # Separate by geometry type
        points = []
        lines = []
        polygons = []


        for idx, drawing in enumerate(drawings):
            shape_type = drawing.get('type', 'unknown')
            coords = drawing.get('coordinates', [])
            
            print(f"\n   🔍 Processing Drawing {idx+1}:")
            print(f"      Type: {shape_type}")
            print(f"      Coords: {coords}")
            print(f"      Coords length: {len(coords)}")
            
            # Build properties dictionary
            props = {
                'type': shape_type,
                'color_r': int(drawing.get('color', (255, 255, 255))[0]),
                'color_g': int(drawing.get('color', (255, 255, 255))[1]),
                'color_b': int(drawing.get('color', (255, 255, 255))[2]),
                'text': str(drawing.get('text', '')),
                'radius': float(drawing.get('radius', 0))
            }
            
            try:
                # ✅ Check for alternative coordinate keys
                coords_empty = False
                try:
                    coords_empty = (coords is None or 
                                (isinstance(coords, list) and len(coords) == 0) or
                                (hasattr(coords, '__len__') and len(coords) == 0))
                except:
                    coords_empty = True
                
                if coords_empty:
                    print(f"      ⚠️ Empty 'coordinates', checking alternatives...")
                    
                    # Check for 'coords' key (your system uses this)
                    for alt_key in ['coords', 'points', 'vertices', 'corners']:
                        if alt_key in drawing:
                            coords = drawing[alt_key]
                            # Convert numpy array to list if needed
                            if hasattr(coords, 'tolist'):
                                coords = coords.tolist() if hasattr(coords, 'tolist') else list(coords)
                            print(f"      ✅ Found coords in '{alt_key}': {len(coords)} points")
                            break
                
                # ✅ Ensure coords is a Python list (convert numpy arrays)
                if hasattr(coords, 'tolist'):
                    coords = coords.tolist() if callable(coords.tolist) else list(coords)
                elif not isinstance(coords, list):
                    try:
                        coords = list(coords)
                    except:
                        coords = []
                
                # ✅ Convert each coordinate from numpy array to list/tuple
                clean_coords = []
                for c in coords:
                    if hasattr(c, 'tolist'):
                        # Numpy array
                        clean_coords.append(tuple(float(x) for x in c.tolist()))
                    elif isinstance(c, (list, tuple)):
                        # Already a list/tuple
                        clean_coords.append(tuple(float(x) for x in c[:2]))  # Use only X, Y
                    else:
                        print(f"      ⚠️ Skipping invalid coordinate: {c}")
                        continue
                
                coords = clean_coords
                
                if not coords or len(coords) < 2:
                    print(f"      ❌ No valid coordinates after conversion")
                    continue
                
                print(f"      ✅ Converted {len(coords)} coordinates")
                
                # ✅ GEOMETRY CREATION (with type mapping)
                
                # Map custom types to standard types
                if shape_type in ['smartline', 'line_segment', 'freehand']:
                    # All line-based drawings → LineString
                    if len(coords) >= 2:
                        line_coords = [c[:2] for c in coords]
                        geom = LineString(line_coords)
                        lines.append({'geometry': geom, **props})
                        print(f"      ✅ Added as LineString ({shape_type} → line)")
                
                elif shape_type == 'polyline':
                    # Polyline → Polygon (closed shape)
                    if len(coords) >= 3:
                        poly_coords = [(c[0], c[1]) for c in coords]
                        # Ensure closed
                        if poly_coords[0] != poly_coords[-1]:
                            poly_coords.append(poly_coords[0])
                        geom = Polygon(poly_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon (closed polyline)")
                        else:
                            geom = geom.buffer(0)
                            if geom.is_valid:
                                polygons.append({'geometry': geom, **props})
                                print(f"      ✅ Fixed and added polygon")
                
                elif shape_type == 'polygon':
                    if len(coords) >= 3:
                        poly_coords = [(c[0], c[1]) for c in coords]
                        geom = Polygon(poly_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon")
                        else:
                            geom = geom.buffer(0)
                            if geom.is_valid:
                                polygons.append({'geometry': geom, **props})
                
                elif shape_type == 'rectangle':
                    if len(coords) == 5:
                        # 5-point closed format
                        rect_coords = [(c[0], c[1]) for c in coords[:4]]
                        geom = Polygon(rect_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon (rectangle)")
                    elif len(coords) >= 2:
                        # 2-corner format
                        p1, p2 = coords[0], coords[1]
                        rect_coords = [
                            (p1[0], p1[1]),
                            (p2[0], p1[1]),
                            (p2[0], p2[1]),
                            (p1[0], p2[1])
                        ]
                        geom = Polygon(rect_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon (rectangle from 2 corners)")
                
                elif shape_type in ['circle', 'text']:
                    # Points
                    if len(coords) >= 1:
                        coord = coords[0]
                        geom = Point(coord[0], coord[1])
                        points.append({'geometry': geom, **props})
                        print(f"      ✅ Added as Point ({shape_type})")
                
                else:
                    print(f"      ⚠️ Unsupported type: {shape_type}")
                    
            except Exception as e:
                print(f"      ❌ Failed to convert {shape_type}: {e}")
                import traceback
                traceback.print_exc()
                continue
                
                # Ensure coords is a list (convert from numpy if needed)
                if hasattr(coords, 'tolist'):
                    coords = coords.tolist() if callable(coords.tolist) else list(coords)
                elif not isinstance(coords, list):
                    coords = list(coords)
                
                # ============================================================
                # POINT GEOMETRIES
                # ============================================================
                if shape_type in ['circle', 'text'] and len(coords) >= 1:
                    coord = coords[0]
                    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                        geom = Point(coord[:2])
                        points.append({'geometry': geom, **props})
                        print(f"      ✅ Added as Point")
                    else:
                        print(f"      ⚠️ Invalid point coordinate: {coord}")
                
                # ============================================================
                # LINE GEOMETRIES
                # ============================================================
                elif shape_type == 'line' and len(coords) >= 2:
                    line_coords = []
                    for c in coords:
                        if isinstance(c, (list, tuple)) and len(c) >= 2:
                            line_coords.append(c[:2])
                    
                    if len(line_coords) >= 2:
                        geom = LineString(line_coords)
                        lines.append({'geometry': geom, **props})
                        print(f"      ✅ Added as LineString with {len(line_coords)} points")
                    else:
                        print(f"      ⚠️ Not enough valid coordinates for line")
                
                elif shape_type in ['polyline', 'freehand'] and len(coords) >= 2:
                    line_coords = []
                    for c in coords:
                        if isinstance(c, (list, tuple)) and len(c) >= 2:
                            line_coords.append(c[:2])
                    
                    if len(line_coords) >= 2:
                        geom = LineString(line_coords)
                        lines.append({'geometry': geom, **props})
                        print(f"      ✅ Added as LineString with {len(line_coords)} points")
                    else:
                        print(f"      ⚠️ Not enough valid coordinates for polyline")
                
                # ============================================================
                # POLYGON GEOMETRIES
                # ============================================================
                elif shape_type == 'polygon' and len(coords) >= 3:
                    poly_coords = []
                    for c in coords:
                        if isinstance(c, (list, tuple)) and len(c) >= 2:
                            poly_coords.append((c[0], c[1]))
                    
                    if len(poly_coords) >= 3:
                        geom = Polygon(poly_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon with {len(poly_coords)} vertices")
                        else:
                            print(f"      ⚠️ Invalid polygon geometry")
                            # Try to fix invalid polygon
                            geom = geom.buffer(0)
                            if geom.is_valid:
                                polygons.append({'geometry': geom, **props})
                                print(f"      ✅ Fixed and added polygon")
                    else:
                        print(f"      ⚠️ Not enough valid points for polygon (need 3+, got {len(poly_coords)})")
                
                elif shape_type == 'rectangle' and len(coords) >= 2:
                    # HANDLE BOTH FORMATS:
                    # Format 1: 2 corner points [p1, p2]
                    # Format 2: 5 points forming closed rectangle [p1, p2, p3, p4, p1]
                    
                    if len(coords) == 5:
                        # Closed rectangle polygon - use first 4 points
                        print(f"      🔍 Rectangle has 5 points (closed polygon), using first 4")
                        rect_coords = []
                        for i in range(4):
                            c = coords[i]
                            # Handle numpy float64 or regular tuples
                            if isinstance(c, (list, tuple)) and len(c) >= 2:
                                # Convert numpy types to regular Python floats
                                x = float(c[0])
                                y = float(c[1])
                                rect_coords.append((x, y))
                            else:
                                print(f"      ⚠️ Invalid coordinate at index {i}: {c}")
                                break
                        
                        if len(rect_coords) == 4:
                            geom = Polygon(rect_coords)
                            if geom.is_valid:
                                polygons.append({'geometry': geom, **props})
                                print(f"      ✅ Added as Polygon (rectangle from 5 points)")
                                print(f"         Corners: {rect_coords}")
                            else:
                                print(f"      ⚠️ Invalid rectangle geometry, attempting to fix...")
                                geom = geom.buffer(0)
                                if geom.is_valid:
                                    polygons.append({'geometry': geom, **props})
                                    print(f"      ✅ Fixed and added polygon")
                        else:
                            print(f"      ⚠️ Could not extract 4 valid corners")
                    
                    else:
                        # Standard 2-corner format
                        p1 = coords[0]
                        p2 = coords[1]
                        
                        # Validate coordinates
                        if not (isinstance(p1, (list, tuple)) and len(p1) >= 2):
                            print(f"      ⚠️ Invalid first corner: {p1}")
                            continue
                        if not (isinstance(p2, (list, tuple)) and len(p2) >= 2):
                            print(f"      ⚠️ Invalid second corner: {p2}")
                            continue
                        
                        # Convert numpy types to regular Python floats
                        x1, y1 = float(p1[0]), float(p1[1])
                        x2, y2 = float(p2[0]), float(p2[1])
                        
                        # Build rectangle from 2 corners
                        rect_coords = [
                            (x1, y1),
                            (x2, y1),
                            (x2, y2),
                            (x1, y2)
                        ]
                        
                        geom = Polygon(rect_coords)
                        if geom.is_valid:
                            polygons.append({'geometry': geom, **props})
                            print(f"      ✅ Added as Polygon (rectangle from 2 corners)")
                            print(f"         Corners: {rect_coords}")
                        else:
                            print(f"      ⚠️ Invalid rectangle geometry")
                
                else:
                    print(f"      ⚠️ Unsupported type '{shape_type}' or insufficient coords (have {len(coords)})")
                    
            except Exception as e:
                print(f"      ❌ Failed to convert {shape_type}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # ============================================================
        # SUMMARY
        # ============================================================
        print(f"\n   📊 Geometry Summary:")
        print(f"      Points: {len(points)}")
        print(f"      Lines: {len(lines)}")
        print(f"      Polygons: {len(polygons)}")
        
        if not (points or lines or polygons):
            print(f"\n   ❌ No valid geometries to export")
            print(f"   💡 Tip: Check how drawings are being stored in app.digitizer.drawings")
            return False
        
        # ============================================================
        # SAVE FILES
        # ============================================================
        from pathlib import Path
        base_path = Path(output_path).with_suffix('')
        
        # Get CRS
        crs = f"EPSG:{app.project_crs_epsg}" if hasattr(app, 'project_crs_epsg') and app.project_crs_epsg else "EPSG:4326"
        print(f"\n   🌍 Using CRS: {crs}")
        
        saved_files = []
        
        # SAVE POINTS
        if points:
            try:
                print(f"\n   💾 Saving points...")
                gdf = gpd.GeoDataFrame(points, crs=crs)
                point_path = f"{base_path}_points.shp"
                gdf.to_file(point_path, driver='ESRI Shapefile')
                saved_files.append(point_path)
                print(f"      ✅ Saved {len(points)} points to: {point_path}")
            except Exception as e:
                print(f"      ❌ Failed to save points: {e}")
                import traceback
                traceback.print_exc()
        
        # SAVE LINES
        if lines:
            try:
                print(f"\n   💾 Saving lines...")
                gdf = gpd.GeoDataFrame(lines, crs=crs)
                line_path = f"{base_path}_lines.shp"
                gdf.to_file(line_path, driver='ESRI Shapefile')
                saved_files.append(line_path)
                print(f"      ✅ Saved {len(lines)} lines to: {line_path}")
            except Exception as e:
                print(f"      ❌ Failed to save lines: {e}")
                import traceback
                traceback.print_exc()
        
        # SAVE POLYGONS
        if polygons:
            try:
                print(f"\n   💾 Saving polygons...")
                gdf = gpd.GeoDataFrame(polygons, crs=crs)
                poly_path = f"{base_path}_polygons.shp"
                gdf.to_file(poly_path, driver='ESRI Shapefile')
                saved_files.append(poly_path)
                print(f"      ✅ Saved {len(polygons)} polygons to: {poly_path}")
            except Exception as e:
                print(f"      ❌ Failed to save polygons: {e}")
                import traceback
                traceback.print_exc()
        
        # ============================================================
        # FINAL SUMMARY
        # ============================================================
        if saved_files:
            print(f"\n   📁 Successfully Saved Files:")
            for f in saved_files:
                print(f"      • {f}")
            print(f"{'='*60}\n")
            return True
        else:
            print(f"\n   ❌ No files were saved")
            print(f"{'='*60}\n")
            return False
        
    except ImportError as e:
        print(f"   ❌ Missing required library: {e}")
        print(f"   💡 Install: pip install geopandas shapely")
        return False
    except Exception as e:
        print(f"   ❌ Shapefile export failed: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# IMPORT FUNCTIONS
# ============================================================================


def import_drawings_from_shapefile(app, input_path: str) -> bool:
    """Import drawings from Shapefile with proper rendering"""
    try:
        import geopandas as gpd
        from pathlib import Path
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING DRAWINGS FROM SHAPEFILE")
        print(f"   Path: {input_path}")
        
        base_path = Path(input_path).with_suffix('')
        
        # Try to load all geometry types
        imported_count = 0
        
        for suffix in ['_points', '_lines', '_polygons', '']:
            try:
                shp_path = f"{base_path}{suffix}.shp"
                if not Path(shp_path).exists():
                    continue
                
                print(f"   📂 Loading: {shp_path}")
                gdf = gpd.read_file(shp_path)
                print(f"   📊 Found {len(gdf)} features")
                
                for idx, row in gdf.iterrows():
                    geom = row.geometry
                    
                    drawing = {
                        'color': (
                            int(row.get('color_r', 255)),
                            int(row.get('color_g', 255)),
                            int(row.get('color_b', 255))
                        ),
                        'text': str(row.get('text', '')),
                        'radius': float(row.get('radius', 0))
                    }
                    
                    if geom.geom_type == 'Point':
                        drawing['type'] = row.get('type', 'circle')
                        drawing['coordinates'] = [[geom.x, geom.y, 0]]
                    
                    elif geom.geom_type == 'LineString':
                        drawing['type'] = row.get('type', 'polyline')
                        drawing['coordinates'] = [
                            [x, y, 0] for x, y in geom.coords
                        ]
                    
                    elif geom.geom_type == 'Polygon':
                        drawing['type'] = row.get('type', 'polygon')
                        coords = list(geom.exterior.coords)[:-1]
                        drawing['coordinates'] = [
                            [x, y, 0] for x, y in coords
                        ]
                    
                    if hasattr(app, 'digitizer'):
                        # Use proper import method
                        if hasattr(app.digitizer, 'add_imported_drawing'):
                            app.digitizer.add_imported_drawing(drawing)
                        else:
                            app.digitizer.add_drawing_from_data(drawing)
                        imported_count += 1
                        print(f"   ✅ Added {drawing['type']} from import")
                        
            except Exception as e:
                print(f"   ⚠️ Could not load {suffix}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # CRITICAL: Force render update
        if imported_count > 0:
            print(f"\n   🎨 Updating display...")
            
            # Try multiple render methods
            if hasattr(app, 'vtk_widget') and app.vtk_widget:
                try:
                    app.vtk_widget.GetRenderWindow().Render()
                    print(f"   ✅ VTK render triggered")
                except:
                    pass
            
            # Try calling update method
            if hasattr(app, 'update_display'):
                try:
                    app.update_display()
                    print(f"   ✅ Display update called")
                except:
                    pass
            
            # Try refresh method
            if hasattr(app, 'refresh'):
                try:
                    app.refresh()
                    print(f"   ✅ Refresh called")
                except:
                    pass
            
            print(f"   ✅ Imported {imported_count} drawings")
        else:
            print(f"   ⚠️ No drawings imported")
        
        print(f"{'='*60}\n")
        
        return imported_count > 0
        
    except ImportError:
        print("   ⚠️ geopandas not installed")
        return False
    except Exception as e:
        print(f"   ❌ Shapefile import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# MAIN EXPORT DIALOG
# ============================================================================

def show_export_dialog(app):
    """
    Show export format selection dialog and perform export.
    """
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QDialogButtonBox
    
    dialog = QDialog(app)
    dialog.setWindowTitle("Export Drawings")
    dialog.setModal(True)
    
    layout = QVBoxLayout()
    
    # Format selection

    shp_radio = QRadioButton("Shapefile")
    shp_radio.setChecked(True)
    tiff_radio = QRadioButton("GeoTIFF")

    layout.addWidget(shp_radio)
    layout.addWidget(tiff_radio)
    # Buttons
    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    
    dialog.setLayout(layout)
    
    if dialog.exec() == QDialog.Accepted:
        # Get base filename from current file
        if hasattr(app, 'last_save_path') and app.last_save_path:
            base_name = Path(app.last_save_path).stem
            base_dir = Path(app.last_save_path).parent
        else:
            base_name = "drawings"
            base_dir = Path.home()
        
        # Determine format and extension
        # Determine format and extension
        if shp_radio.isChecked():
            ext = "shp"
            filter_str = "Shapefile (*.shp)"
        else:
            ext = "tif"
            filter_str = "GeoTIFF Files (*.tif *.tiff)"
        # File dialog
        output_path, _ = QFileDialog.getSaveFileName(
            app,
            "Export Drawings",
            str(base_dir / f"{base_name}_drawings.{ext}"),
            filter_str
        )
        
        if output_path:
            # Perform export
            success = False
            if shp_radio.isChecked():
                success = export_drawings_to_shapefile(app, output_path)
            else:
                success = export_drawings_to_tiff(app, output_path)
            
            if success:
                QMessageBox.information(
                    app,
                    "Export Successful",
                    f"Drawings exported to:\n{output_path}"
                )
            else:
                QMessageBox.warning(
                    app,
                    "Export Failed",
                    "Failed to export drawings. Check console for details."
                )

import vtk
import numpy as np

def create_vtk_actor_from_drawing(drawing, renderer ,z_offset=10.0):
    """
    Create a VTK actor from drawing data and add it to the renderer.
    Returns the actor so it can be stored in the drawing dict.
    """
    shape_type = drawing.get('type', 'unknown')
    coords = drawing.get('coordinates', [])
    color = drawing.get('color', (255, 255, 255))
    if z_offset != 0:
        coords = [[c[0], c[1], (c[2] if len(c) > 2 else 0) + z_offset] for c in coords]
    
    # Normalize color to 0-1 range
    color_norm = tuple(c / 255.0 for c in color)
    
    actor = None
    
    try:
        # ============================================================
        # CIRCLE
        # ============================================================
        if shape_type == 'circle' and len(coords) >= 1:
            center = coords[0]
            radius = drawing.get('radius', 5.0)
            
            # Create circle using vtkRegularPolygonSource
            circle_source = vtk.vtkRegularPolygonSource()
            circle_source.SetNumberOfSides(32)
            circle_source.SetRadius(radius)
            circle_source.SetCenter(center[0], center[1], center[2] if len(center) > 2 else 0)
            circle_source.GeneratePolygonOff()  # Just the outline
            circle_source.Update()
            
            # Create mapper and actor
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(circle_source.GetOutputPort())
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.GetProperty().SetLineWidth(3)  # Thicker for visibility
            actor.GetProperty().SetRepresentationToWireframe()
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
        
        # ============================================================
        # LINE
        # ============================================================
        elif shape_type == 'line' and len(coords) >= 2:
            points = vtk.vtkPoints()
            for coord in coords:
                points.InsertNextPoint(
                    coord[0], 
                    coord[1], 
                    coord[2] if len(coord) > 2 else 0
                )
            
            line = vtk.vtkPolyLine()
            line.GetPointIds().SetNumberOfIds(len(coords))
            for i in range(len(coords)):
                line.GetPointIds().SetId(i, i)
            
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(line)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetLines(cells)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.GetProperty().SetLineWidth(3)  # Thicker for visibility
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
        
        # ============================================================
        # POLYLINE / FREEHAND
        # ============================================================
        elif shape_type in ['polyline', 'freehand'] and len(coords) >= 2:
            points = vtk.vtkPoints()
            for coord in coords:
                points.InsertNextPoint(
                    coord[0], 
                    coord[1], 
                    coord[2] if len(coord) > 2 else 0
                )
            
            polyline = vtk.vtkPolyLine()
            polyline.GetPointIds().SetNumberOfIds(len(coords))
            for i in range(len(coords)):
                polyline.GetPointIds().SetId(i, i)
            
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(polyline)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetLines(cells)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.GetProperty().SetLineWidth(3)  # Thicker for visibility
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
        
        # ============================================================
        # POLYGON
        # ============================================================
        elif shape_type == 'polygon' and len(coords) >= 3:
            points = vtk.vtkPoints()
            for coord in coords:
                points.InsertNextPoint(
                    coord[0], 
                    coord[1], 
                    coord[2] if len(coord) > 2 else 0
                )
            
            polygon = vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(len(coords))
            for i in range(len(coords)):
                polygon.GetPointIds().SetId(i, i)
            
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(polygon)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetPolys(cells)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.GetProperty().SetLineWidth(3)  # Thicker for visibility
            actor.GetProperty().SetRepresentationToWireframe()
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
        
        # ============================================================
        # RECTANGLE
        # ============================================================
        elif shape_type == 'rectangle' and len(coords) >= 2:
            p1, p2 = coords[0], coords[1]
            
            # Create 4 corners
            rect_coords = [
                [p1[0], p1[1], p1[2] if len(p1) > 2 else 0],
                [p2[0], p1[1], p1[2] if len(p1) > 2 else 0],
                [p2[0], p2[1], p2[2] if len(p2) > 2 else 0],
                [p1[0], p2[1], p2[2] if len(p2) > 2 else 0]
            ]
            
            points = vtk.vtkPoints()
            for coord in rect_coords:
                points.InsertNextPoint(coord[0], coord[1], coord[2])
            
            polygon = vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(4)
            for i in range(4):
                polygon.GetPointIds().SetId(i, i)
            
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(polygon)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetPolys(cells)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.GetProperty().SetLineWidth(3)  # Thicker for visibility
            actor.GetProperty().SetRepresentationToWireframe()
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
            
            # Print rectangle bounds for debugging
            print(f"       Rectangle bounds: X({p1[0]:.1f} to {p2[0]:.1f}), Y({p1[1]:.1f} to {p2[1]:.1f})")
        
        # ============================================================
        # TEXT (simplified as a sphere marker)
        # ============================================================
        elif shape_type == 'text' and len(coords) >= 1:
            pos = coords[0]
            
            sphere = vtk.vtkSphereSource()
            sphere.SetCenter(pos[0], pos[1], pos[2] if len(pos) > 2 else 0)
            sphere.SetRadius(5.0)  # Larger for visibility
            sphere.SetThetaResolution(16)
            sphere.SetPhiResolution(16)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(sphere.GetOutputPort())
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*color_norm)
            actor.VisibilityOn()  # Ensure visibility
            actor.PickableOn()    # Enable picking
        
        # Add actor to renderer and verify
        if actor and renderer:
            renderer.AddActor(actor)
            
            # Verify actor was added
            num_actors = renderer.GetActors().GetNumberOfItems()
            print(f"   ✅ VTK actor created and added to renderer for {shape_type}")
            print(f"       Total actors in renderer: {num_actors}")
            print(f"       Actor visibility: {actor.GetVisibility()}")
            print(f"       Actor color: {actor.GetProperty().GetColor()}")
            
            return actor
        else:
            print(f"   ⚠️ Failed to create actor for {shape_type}")
            return None
            
    except Exception as e:
        print(f"   ❌ Error creating VTK actor for {shape_type}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    
def import_drawings_from_shapefile_with_rendering(app, input_path: str) -> bool:
    """
    Import shapefile and ensure VTK actors are created and visible
    """
    try:
        import geopandas as gpd
        from pathlib import Path
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING DRAWINGS FROM SHAPEFILE")
        print(f"   Path: {input_path}")
        
        # ✅ Verify digitizer exists
        if not hasattr(app, 'digitizer'):
            print(f"   ❌ app.digitizer does not exist!")
            return False
        
        if not app.digitizer:
            print(f"   ❌ app.digitizer is None!")
            return False
        
        if not hasattr(app.digitizer, 'add_drawing_from_data'):
            print(f"   ❌ app.digitizer.add_drawing_from_data method does not exist!")
            return False
        
        print(f"   ✅ Digitizer found and ready")
        
        base_path = Path(input_path).with_suffix('')
        imported_count = 0
        failed_count = 0
        
        # Try to load all geometry types
        for suffix in ['_points', '_lines', '_polygons', '']:
            try:
                shp_path = f"{base_path}{suffix}.shp"
                if not Path(shp_path).exists():
                    continue
                
                print(f"\n   📂 Loading: {shp_path}")
                gdf = gpd.read_file(shp_path)
                print(f"   📊 Found {len(gdf)} features")
                
                for idx, row in gdf.iterrows():
                    try:
                        geom = row.geometry
                        
                        # Build drawing data dict
                        drawing_data = {
                            'color': (
                                int(row.get('color_r', 255)),
                                int(row.get('color_g', 255)),
                                int(row.get('color_b', 255))
                            ),
                            'text': str(row.get('text', '')),
                            'radius': float(row.get('radius', 5.0))
                        }
                        
                        # Convert geometry to coordinates
                        if geom.geom_type == 'Point':
                            drawing_data['type'] = str(row.get('type', 'circle'))
                            drawing_data['coordinates'] = [[float(geom.x), float(geom.y), 0.0]]
                        
                        elif geom.geom_type == 'LineString':
                            drawing_data['type'] = str(row.get('type', 'polyline'))
                            drawing_data['coordinates'] = [
                                [float(x), float(y), 0.0] for x, y in geom.coords
                            ]
                        
                        elif geom.geom_type == 'Polygon':
                            drawing_data['type'] = str(row.get('type', 'polygon'))
                            # ✅ Keep ALL points including closing point
                            coords = list(geom.exterior.coords)
                            drawing_data['coordinates'] = [
                                [float(x), float(y), 0.0] for x, y in coords
                            ]
                        
                        else:
                            print(f"      ⚠️ Unsupported geometry type: {geom.geom_type}")
                            failed_count += 1
                            continue
                        
                        # ✅ USE DIGITIZER METHOD (not direct actor creation)
                        print(f"      🔄 Importing {drawing_data['type']}...")
                        
                        try:
                            success = app.digitizer.add_drawing_from_data(drawing_data)
                            
                            if success:
                                imported_count += 1
                            else:
                                failed_count += 1
                        except Exception as e:
                            failed_count += 1
                            print(f"      ❌ Exception: {e}")
                            import traceback
                            traceback.print_exc()
                        
                    except Exception as e:
                        failed_count += 1
                        print(f"      ❌ Failed to process feature: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                        
            except Exception as e:
                print(f"   ⚠️ Could not load {suffix}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # Summary
        print(f"\n   📊 Import Summary:")
        print(f"      Successful: {imported_count}")
        print(f"      Failed: {failed_count}")
        
        # Force render
        if imported_count > 0:
            print(f"\n   🎨 Rendering scene...")
            
            try:
                if hasattr(app, 'vtk_widget') and app.vtk_widget:
                    app.vtk_widget.GetRenderWindow().Render()
                    print(f"   ✅ Render complete")
            except Exception as e:
                print(f"   ⚠️ Render error: {e}")
        
        print(f"{'='*60}\n")
        
        return imported_count > 0
        
    except ImportError as e:
        print(f"   ❌ Missing library: {e}")
        print(f"   💡 Install: pip install geopandas shapely")
        return False
    except Exception as e:
        print(f"   ❌ Shapefile import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
def show_import_dialog(app):
    """Show import dialog with texture option and multiple file selection"""
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QRadioButton, 
        QDialogButtonBox, QFileDialog, QMessageBox, QProgressDialog
    )
    from PySide6.QtCore import Qt, QCoreApplication
    from pathlib import Path
    
    dialog = QDialog(app)
    dialog.setWindowTitle("Import Drawings")
    dialog.setModal(True)
    
    layout = QVBoxLayout()
    
    # Format selection
    shp_radio = QRadioButton("Shapefile (Vector)")
    tiff_texture_radio = QRadioButton("GeoTIFF (Textured Surface)")
    tiff_vector_radio = QRadioButton("GeoTIFF (Vectorized)")
    
    tiff_texture_radio.setChecked(True)  # Default to texture
    
    layout.addWidget(shp_radio)
    layout.addWidget(tiff_texture_radio)
    layout.addWidget(tiff_vector_radio)
    
    # Buttons
    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    
    dialog.setLayout(layout)
    
    if dialog.exec() == QDialog.Accepted:
        # Determine filter
        if shp_radio.isChecked():
            filter_str = "Shapefile (*.shp)"
        else:
            filter_str = "GeoTIFF Files (*.tif *.tiff)"
        
        # ✅ MULTIPLE FILE SELECTION
        input_paths, _ = QFileDialog.getOpenFileNames(
            app,
            "Import Files (Multiple Selection Enabled)",
            str(Path.home()),
            filter_str
        )
        
        if not input_paths:
            return  # User cancelled
        
        # Process multiple files
        total_files = len(input_paths)
        successful = 0
        failed = 0
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING {total_files} FILE(S)")
        print(f"{'='*60}")
        
        # Progress dialog for multiple files
        progress = QProgressDialog(
            f"Importing files...",
            "Cancel",
            0,
            total_files,
            app
        )
        progress.setWindowTitle("Import Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        
        for idx, input_path in enumerate(input_paths):
            if progress.wasCanceled():
                print(f"\n⚠️ Import cancelled by user")
                break
            
            progress.setValue(idx)
            progress.setLabelText(f"Importing {idx+1}/{total_files}: {Path(input_path).name}")
            QCoreApplication.processEvents()
            
            print(f"\n📂 File {idx+1}/{total_files}: {Path(input_path).name}")
            
            try:
                success = False
                
                if shp_radio.isChecked():
                    success = import_drawings_from_shapefile_with_rendering(app, input_path)
                elif tiff_texture_radio.isChecked():
                    success = import_geotiff_as_texture(app, input_path)
                else:
                    success = import_drawings_from_tiff(app, input_path)
                
                if success:
                    successful += 1
                    print(f"✅ Success")
                else:
                    failed += 1
                    print(f"❌ Failed")
                    
            except Exception as e:
                failed += 1
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
        
        progress.setValue(total_files)
        progress.close()
        
        # Summary message
        print(f"\n{'='*60}")
        print(f"📊 IMPORT SUMMARY")
        print(f"   Total files: {total_files}")
        print(f"   ✅ Successful: {successful}")
        print(f"   ❌ Failed: {failed}")
        print(f"{'='*60}\n")
        
        if successful > 0:
            QMessageBox.information(
                app,
                "Import Complete",
                f"Successfully imported {successful} of {total_files} file(s).\n\n"
                f"✅ Successful: {successful}\n"
                f"❌ Failed: {failed}\n\n"
                f"Check console for details."
            )
        else:
            QMessageBox.warning(
                app,
                "Import Failed",
                f"Failed to import all {total_files} file(s).\n\n"
                f"Check console for details."
            )
        
        
   
def export_drawings_to_tiff(app, output_path: str) -> bool:
    """
    Export drawings AND point cloud data to GeoTIFF format.
    Creates a raster with point cloud as background and drawings overlaid.
    """
    try:
        import rasterio
        from rasterio.features import rasterize
        from shapely.geometry import Point, LineString, Polygon
        import numpy as np
        print("✅ All imports successful")
        
        # Now run diagnostics
        try:
            diagnose_app_data(app)
        except Exception as e:
            print(f"❌ Diagnostic failed: {e}")
            import traceback
            traceback.print_exc()
        # ADD THIS LINE HERE:
        
        print(f"\n{'='*60}")
        print(f"📤 EXPORTING TO TIFF (Point Cloud + Drawings)")
        print(f"   Path: {output_path}")
        
        # ============================================================
        # STEP 1: Get Point Cloud Data
        # ============================================================
        point_cloud_data = None

        print(f"\n   🔍 SEARCHING FOR POINT CLOUD DATA:")

        # Try common attribute names
        for attr_name in ['point_cloud', 'points', 'cloud', 'pc', 'vtk_points', 
                        'point_data', 'xyz_data', 'las_points', 'filtered_points',
                        'original_points', 'loaded_points']:
            if hasattr(app, attr_name):
                val = getattr(app, attr_name)
                print(f"   • Found app.{attr_name}: {type(val)}")
                
                if val is not None:
                    # Check if it's a VTK object
                    if hasattr(val, 'GetNumberOfPoints'):
                        num_points = val.GetNumberOfPoints()
                        print(f"      → VTK PolyData with {num_points} points")
                        # Extract points from VTK
                        point_cloud_data = []
                        for i in range(num_points):
                            pt = val.GetPoint(i)
                            point_cloud_data.append(pt)
                        print(f"   ✅ Extracted {len(point_cloud_data)} points from VTK")
                        break
                    
                    # Check if it's a numpy array
                    elif hasattr(val, 'shape'):
                        print(f"      → NumPy array: shape {val.shape}")
                        if len(val.shape) >= 2 and val.shape[1] >= 2:
                            point_cloud_data = val
                            print(f"   ✅ Using numpy array: {len(point_cloud_data)} points")
                            break
                    
                    # Check if it's a list
                    elif isinstance(val, list) and len(val) > 0:
                        print(f"      → List with {len(val)} items")
                        # Check if first item looks like a point
                        if len(val) > 0 and hasattr(val[0], '__len__') and len(val[0]) >= 2:
                            point_cloud_data = val
                            print(f"   ✅ Using list: {len(point_cloud_data)} points")
                            break
                        
        # ✅ ADD THE VTK CHECK HERE - RIGHT AFTER THE FOR LOOP ENDS
        # ✅ Check VTK widget for point cloud
        # ✅ Check VTK widget for point cloud (improved version)
        if point_cloud_data is None and hasattr(app, 'vtk_widget'):
            print(f"   • Searching ALL VTK actors for point clouds...")
            try:
                renderer = app.vtk_widget.GetRenderWindow().GetRenderers().GetFirstRenderer()
                actors = renderer.GetActors()
                actors.InitTraversal()
                
                largest_actor = None
                max_points = 0
                
                for i in range(actors.GetNumberOfItems()):
                    actor = actors.GetNextActor()
                    if not actor:
                        continue
                        
                    mapper = actor.GetMapper()
                    if not mapper:
                        continue
                        
                    input_data = mapper.GetInput()
                    if not input_data or not hasattr(input_data, 'GetNumberOfPoints'):
                        continue
                    
                    num_points = input_data.GetNumberOfPoints()
                    print(f"      → Actor {i}: {num_points} points")
                    
                    # Track largest actor (likely the point cloud)
                    if num_points > max_points:
                        max_points = num_points
                        largest_actor = input_data
                
                # Use largest actor if it has many points (likely point cloud)
                if largest_actor and max_points > 100:
                    print(f"      → Using largest actor: {max_points} points")
                    point_cloud_data = []
                    for j in range(max_points):
                        pt = largest_actor.GetPoint(j)
                        point_cloud_data.append(pt)
                    print(f"   ✅ Extracted {len(point_cloud_data)} points from VTK renderer")
            except Exception as e:
                print(f"      ⚠️ Error searching VTK actors: {e}")
                import traceback
                traceback.print_exc()

        # This line stays where it is
        if point_cloud_data is None:
            print(f"   ⚠️ No point cloud data found in any standard location")
        else:
            print(f"   ✅ Point cloud data loaded: {len(point_cloud_data)} points")
        
        
        # ============================================================
        # STEP 2: Get Drawings
        # ============================================================
        drawings = []
        if hasattr(app, 'digitizer') and app.digitizer:
            drawings = app.digitizer.drawings or []
            print(f"   📊 Drawings found: {len(drawings)}")
        else:
            print(f"   ⚠️ No drawings found")
        
        # Check if we have ANY data to export
        if point_cloud_data is None and not drawings:
            print(f"   ❌ No data to export (no point cloud or drawings)")
            return False
        
        # ============================================================
        # STEP 3: Calculate Bounds
        # ============================================================
        # ============================================================
        # STEP 3: Calculate Bounds
        # ============================================================
        all_coords = []

        # Add point cloud coordinates
        if point_cloud_data is not None:
            if hasattr(point_cloud_data, 'shape'):
                # NumPy array format
                if len(point_cloud_data.shape) == 2 and point_cloud_data.shape[1] >= 2:
                    all_coords.extend([(p[0], p[1]) for p in point_cloud_data[:, :2]])
            elif isinstance(point_cloud_data, list):
                # List format
                all_coords.extend([(p[0], p[1]) for p in point_cloud_data if len(p) >= 2])

        # Add drawing coordinates with diagnostics
        print(f"\n   🔍 EXTRACTING DRAWING COORDINATES:")
        for idx, drawing in enumerate(drawings):
            print(f"\n   Drawing {idx+1}:")
            print(f"      Type: {drawing.get('type', 'unknown')}")
            print(f"      Keys: {list(drawing.keys())}")
            
            # Try multiple possible coordinate keys
            coords = None
            for key in ['coordinates', 'coords', 'points', 'vertices']:
                if key in drawing:
                    coords = drawing[key]
                    print(f"      ✅ Found '{key}': {type(coords)}")
                    
                    # Handle numpy arrays
                    if hasattr(coords, 'tolist'):
                        coords = coords.tolist()
                        print(f"      → Converted from numpy to list")
                    
                    # Show first few coordinates
                    if coords and len(coords) > 0:
                        print(f"      → Length: {len(coords)}")
                        print(f"      → First coord: {coords[0]}")
                        if len(coords) > 1:
                            print(f"      → Last coord: {coords[-1]}")
                    
                    break
            
            if coords is None:
                print(f"      ⚠️ No coordinates found with any key!")
                print(f"      Full drawing data: {drawing}")
                continue
            
            # Extract valid coordinates
            extracted = 0
            for c in coords:
                try:
                    if hasattr(c, 'tolist'):
                        c = c.tolist()
                    
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        all_coords.append((float(c[0]), float(c[1])))
                        extracted += 1
                except Exception as e:
                    print(f"      ⚠️ Failed to extract coord {c}: {e}")
                    continue
            
            print(f"      ✅ Extracted {extracted} valid coordinates")

        print(f"\n   📊 Total coordinates collected: {len(all_coords)}")

        if not all_coords:
            print(f"   ❌ No valid coordinates found")
            print(f"\n   💡 TIP: Check the drawing structure above")
            return False

        xs, ys = zip(*all_coords)
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)

        # Add 10% buffer
        buffer = max((maxx - minx), (maxy - miny)) * 0.1
        minx -= buffer
        maxx += buffer
        miny -= buffer
        maxy += buffer

        print(f"   📐 Bounds: X({minx:.2f} to {maxx:.2f}), Y({miny:.2f} to {maxy:.2f})")
        # ============================================================
        # STEP 4: Set Resolution and Create Transform
        # ============================================================
        # ============================================================
        # STEP 4: Set Resolution and Create Transform
        # ============================================================
        # Calculate extent
        extent_x = maxx - minx
        extent_y = maxy - miny

        print(f"   📏 Extent: X={extent_x:.2f}m, Y={extent_y:.2f}m")

        # Auto-calculate resolution to get reasonable image size
        target_pixels = 2000  # Target size for larger dimension
        resolution = max(extent_x, extent_y) / target_pixels

        # Minimum resolution to prevent huge files
        min_resolution = 0.1
        resolution = max(resolution, min_resolution)

        width = int(extent_x / resolution)
        height = int(extent_y / resolution)

        # Ensure minimum size
        if width < 10:
            width = 10
            resolution = extent_x / width
        if height < 10:
            height = 10
            resolution = max(resolution, extent_y / height)

        # Limit maximum size to prevent memory issues
        max_dimension = 10000
        if width > max_dimension:
            width = max_dimension
            resolution = extent_x / width
        if height > max_dimension:
            height = max_dimension
            resolution = max(resolution, extent_y / height)

        # Recalculate final dimensions
        width = max(10, int(extent_x / resolution))
        height = max(10, int(extent_y / resolution))

        print(f"   📐 Raster size: {width}x{height} pixels @ {resolution:.3f}m/pixel")

        if width <= 0 or height <= 0:
            print(f"   ❌ Invalid raster dimensions: {width}x{height}")
            return False

        from rasterio.transform import from_bounds
        transform = from_bounds(minx, miny, maxx, maxy, width, height)
        
        # ============================================================
        # STEP 5: Rasterize Point Cloud (Background Layer)
        # ============================================================
        raster = np.zeros((height, width), dtype=np.uint8)
        
        if point_cloud_data is not None:
            print(f"   🔄 Rasterizing point cloud...")
            
            for point in point_cloud_data:
                try:
                    x, y = point[0], point[1]
                    
                    # Convert world coords to pixel coords
                    col = int((x - minx) / resolution)
                    row = int((maxy - y) / resolution)
                    
                    if 0 <= row < height and 0 <= col < width:
                        raster[row, col] = 128  # Gray for point cloud
                except:
                    continue
            
            print(f"   ✅ Point cloud rasterized")
        
        # ============================================================
        # STEP 6: Rasterize Drawings (Overlay Layer)
        # ============================================================
        if drawings:
            print(f"   🔄 Rasterizing {len(drawings)} drawings...")
            
            shapes = []
            for drawing in drawings:
                shape_type = drawing.get('type')
                coords = drawing.get('coords', drawing.get('coordinates', []))
                
                try:
                    if shape_type in ['circle', 'text'] and len(coords) >= 1:
                        geom = Point(coords[0][:2])
                        shapes.append((geom.buffer(2.0), 255))  # White dots
                    
                    elif shape_type in ['line', 'polyline', 'freehand', 'smartline', 'line_segment'] and len(coords) >= 2:
                        geom = LineString([c[:2] for c in coords])
                        shapes.append((geom.buffer(0.5), 255))  # White lines
                    
                    elif shape_type in ['polygon', 'rectangle'] and len(coords) >= 3:
                        poly_coords = [c[:2] for c in coords]
                        if poly_coords[0] != poly_coords[-1]:
                            poly_coords.append(poly_coords[0])
                        geom = Polygon(poly_coords)
                        shapes.append((geom, 255))  # White polygons
                except Exception as e:
                    print(f"   ⚠️ Failed to rasterize {shape_type}: {e}")
                    continue
            
            if shapes:
                drawing_raster = rasterize(
                    shapes,
                    out_shape=(height, width),
                    transform=transform,
                    fill=0,
                    dtype=np.uint8
                )
                
                # Overlay drawings on point cloud (drawings take priority)
                raster = np.where(drawing_raster > 0, drawing_raster, raster)
                print(f"   ✅ Drawings overlaid")
        
        # ============================================================
        # STEP 7: Write GeoTIFF
        # ============================================================
        crs = f"EPSG:{app.project_crs_epsg}" if hasattr(app, 'project_crs_epsg') and app.project_crs_epsg else "EPSG:4326"
        print(f"   🌍 Using CRS: {crs}")
        
        with rasterio.open(
            output_path,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=raster.dtype,
            crs=crs,
            transform=transform,
            compress='lzw'
        ) as dst:
            dst.write(raster, 1)
        
        print(f"   ✅ TIFF export successful!")
        print(f"   📊 Summary:")
        print(f"      - Point cloud: {'Yes' if point_cloud_data is not None else 'No'}")
        print(f"      - Drawings: {len(drawings)}")
        print(f"      - Size: {width}x{height} pixels")
        print(f"{'='*60}\n")
        return True
        
    except ImportError as e:
        print(f"   ⚠️ Missing library: {e}")
        print(f"   💡 Install: pip install rasterio shapely")
        return False
    except Exception as e:
        print(f"   ❌ TIFF export failed: {e}")
        import traceback
        traceback.print_exc()
        return False

# def import_drawings_from_tiff(app, input_path: str) -> bool:
#     """
#     Import drawings from GeoTIFF - vectorizes raster data.
#     """
#     # FIRST: Confirm function is called
#     print("\n" + "="*60)
#     print("🚀 IMPORT_DRAWINGS_FROM_TIFF CALLED")
#     print(f"   Input path: {input_path}")
#     print("="*60)
#     try:
#         import rasterio
#         from rasterio.features import shapes
#         from shapely.geometry import shape, Polygon
        
#         print(f"\n{'='*60}")
#         print(f"📥 IMPORTING DRAWINGS FROM TIFF")
#         print(f"   Path: {input_path}")
        
#         # Verify file exists
#         from pathlib import Path
#         if not Path(input_path).exists():
#             print(f"   ❌ File does not exist: {input_path}")
#             return False
        
#         print(f"   📂 Opening TIFF file...")
#         with rasterio.open(input_path) as src:
#             print(f"   ✅ TIFF opened successfully")
#             print(f"   📊 Raster info:")
#             print(f"      - Size: {src.width}x{src.height}")
#             print(f"      - Bands: {src.count}")
#             print(f"      - CRS: {src.crs}")
#             print(f"      - Bounds: {src.bounds}")
            
#             # Read first band
#             image = src.read(1)
#             transform = src.transform
            
#             print(f"   🔍 Raster value range: {image.min()} to {image.max()}")
            
#             # Check if raster has any non-zero values
#             non_zero = (image > 0).sum()
#             print(f"   📊 Non-zero pixels: {non_zero} / {image.size}")
            
#             if non_zero == 0:
#                 print(f"   ⚠️ TIFF is empty (all pixels are zero)")
#                 return False
            
#             # Vectorize raster
#             print(f"   🔄 Vectorizing raster data...")
#             mask = image > 0
#             results = list(shapes(image, mask=mask, transform=transform))
            
#             print(f"   ✅ Found {len(results)} shapes")
            
#             if not results:
#                 print(f"   ⚠️ No shapes extracted from TIFF")
#                 return False
            
#             imported_count = 0
#             failed_count = 0
            
#             for idx, (geom, value) in enumerate(results):
#                 try:
#                     poly = shape(geom)
                    
#                     print(f"   🔍 Processing shape {idx+1}:")
#                     print(f"      Geometry type: {poly.geom_type}")
#                     print(f"      Area: {poly.area:.6f}")
#                     print(f"      Pixel value: {value}")
                    
#                     # Skip very small polygons (noise)
#                     if poly.area < 0.0001:
#                         print(f"      ⚠️ Skipped (area too small: {poly.area:.6f})")
#                         continue
                    
#                     # Convert to drawing format
#                     if poly.geom_type == 'Polygon':
#                         coords = list(poly.exterior.coords)
#                         print(f"      → Polygon has {len(coords)} coordinates")
#                         print(f"      → First coord: {coords[0]}")
#                         print(f"      → Last coord: {coords[-1]}")
                        
#                         drawing = {
#                             'type': 'polygon',
#                             'coordinates': [[float(x), float(y), 0.0] for x, y in coords[:-1]],
#                             'color': (255, 255, 0)  # Yellow for imported
#                         }
                        
#                         print(f"      → Drawing dict created: {len(drawing['coordinates'])} coords")
                        
#                         if hasattr(app, 'digitizer') and app.digitizer:
#                             print(f"      → Calling app.digitizer.add_drawing_from_data...")
#                             success = app.digitizer.add_drawing_from_data(drawing)
#                             print(f"      → Result: {success}")
                            
#                             if success:
#                                 imported_count += 1
#                                 print(f"      ✅ Successfully imported")
#                             else:
#                                 failed_count += 1
#                                 print(f"      ❌ Failed to import")
#                         else:
#                             print(f"      ❌ No digitizer found")
#                             return False
                    
#                     elif poly.geom_type == 'MultiPolygon':
#                         print(f"      → MultiPolygon with {len(poly.geoms)} parts")
#                         # Handle multipolygons
#                         for sub_idx, sub_poly in enumerate(poly.geoms):
#                             coords = list(sub_poly.exterior.coords)
#                             print(f"         Part {sub_idx+1}: {len(coords)} coordinates, area: {sub_poly.area:.6f}")
                            
#                             if sub_poly.area < 0.0001:
#                                 print(f"         ⚠️ Skipped (area too small)")
#                                 continue
                            
#                             drawing = {
#                                 'type': 'polygon',
#                                 'coordinates': [[float(x), float(y), 0.0] for x, y in coords[:-1]],
#                                 'color': (255, 255, 0)
#                             }
                            
#                             if hasattr(app, 'digitizer') and app.digitizer:
#                                 success = app.digitizer.add_drawing_from_data(drawing)
#                                 if success:
#                                     imported_count += 1
#                                     print(f"         ✅ Successfully imported")
#                                 else:
#                                     failed_count += 1
#                                     print(f"         ❌ Failed to import")
#                     else:
#                         print(f"      ⚠️ Unsupported geometry type: {poly.geom_type}")
                
#                 except Exception as e:
#                     failed_count += 1
#                     print(f"   ❌ Failed to import shape {idx}: {e}")
#                     import traceback
#                     traceback.print_exc()
#                     continue
        
#         # Force render update
#         if imported_count > 0:
#             print(f"\n   🎨 Updating display...")
#             if hasattr(app, 'vtk_widget') and app.vtk_widget:
#                 app.vtk_widget.GetRenderWindow().Render()
            
#             print(f"\n   ✅ Import Summary:")
#             print(f"      - Successful: {imported_count}")
#             print(f"      - Failed: {failed_count}")
#         else:
#             print(f"\n   ⚠️ No drawings imported")
        
#         print(f"{'='*60}\n")
        
#         return imported_count > 0
        
#     except ImportError as e:
#         print(f"   ❌ Missing library: {e}")
#         print(f"   💡 Install: pip install rasterio shapely")
#         return False
#     except Exception as e:
#         print(f"   ❌ TIFF import failed: {e}")
#         import traceback
#         traceback.print_exc()
#         return False

def import_drawings_from_tiff(app, input_path: str) -> bool:
    """
    Import drawings from GeoTIFF - optimized with progress bar for large files.
    """
    try:
        import rasterio
        from rasterio.features import shapes
        from shapely.geometry import shape
        from pathlib import Path
        from PySide6.QtWidgets import QProgressDialog, QMessageBox
        from PySide6.QtCore import Qt, QCoreApplication
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING DRAWINGS FROM TIFF")
        print(f"   Path: {input_path}")
        
        # Verify file exists
        if not Path(input_path).exists():
            print(f"   ❌ File does not exist: {input_path}")
            return False
        
        # ============================================================
        # STEP 1: Read TIFF with progress dialog (RGB Support)
        # ============================================================
        progress = QProgressDialog("Loading GeoTIFF...", "Cancel", 0, 100, app)
        progress.setWindowTitle("Import GeoTIFF")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(5)
        QCoreApplication.processEvents()
        
        with rasterio.open(input_path) as src:
            print(f"   📊 Raster: {src.width}x{src.height} @ {src.crs}")
            print(f"   📊 Bands: {src.count}")
            
            # ✅ READ RGB BANDS if available
            is_rgb = src.count >= 3
            
            if is_rgb:
                print(f"   🎨 Detected RGB GeoTIFF")
                red = src.read(1)
                green = src.read(2)
                blue = src.read(3)
                
                # Create composite image for vectorization
                # Use intensity (average of RGB) to detect features
                image = (red.astype(np.float32) + green.astype(np.float32) + blue.astype(np.float32)) / 3
                image = image.astype(np.uint8)
            else:
                print(f"   ⚫ Single-band GeoTIFF")
                image = src.read(1)
                red = green = blue = None
            
            transform = src.transform
            
            # Quick check for data
            non_zero = (image > 0).sum()
            if non_zero == 0:
                progress.close()
                print(f"   ⚠️ TIFF is empty")
                return False
            
            progress.setLabelText(f"Vectorizing {non_zero:,} pixels...")
            progress.setValue(10)
            QCoreApplication.processEvents()
            
            print(f"   🔄 Vectorizing {non_zero:,} pixels...")
            
            # Use connectivity=8 for better grouping
            mask = image > 0
            results = list(shapes(image, mask=mask, transform=transform, connectivity=8))
            
            print(f"   📦 Found {len(results):,} raw shapes")
        
        if progress.wasCanceled():
            progress.close()
            return False
        
        progress.setValue(20)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 2: AGGRESSIVE FILTERING for large datasets
        # ============================================================
        pixel_area = abs(transform[0] * transform[4])  # dx * dy
        
        # Dynamic threshold based on shape count
        if len(results) > 100000:
            # Very large file - use aggressive filtering
            min_area = pixel_area * 500  # At least 500 pixels (~22x22)
            print(f"   ⚠️ Large dataset detected ({len(results):,} shapes)")
            print(f"   🔍 Using aggressive filter: minimum area = {min_area:.4f}")
        elif len(results) > 10000:
            # Large file - moderate filtering
            min_area = pixel_area * 100  # At least 100 pixels (~10x10)
            print(f"   🔍 Using moderate filter: minimum area = {min_area:.4f}")
        else:
            # Small file - gentle filtering
            min_area = pixel_area * 25  # At least 25 pixels (5x5)
            print(f"   🔍 Using gentle filter: minimum area = {min_area:.4f}")
        
        progress.setLabelText(f"Filtering {len(results):,} shapes...")
        progress.setValue(30)
        QCoreApplication.processEvents()
        
        # Pre-filter by area (fast calculation without full geometry)
        filtered_results = []
        for g, v in results:
            try:
                poly = shape(g)
                if poly.area >= min_area:
                    # ✅ EXTRACT COLOR from RGB bands at polygon centroid
                    color = (255, 255, 0)  # Default yellow
                    
                    if is_rgb and red is not None:
                        try:
                            # Get centroid of polygon
                            centroid = poly.centroid
                            
                            # Convert to pixel coordinates
                            col = int((centroid.x - transform[2]) / transform[0])
                            row = int((centroid.y - transform[5]) / transform[4])
                            
                            # Ensure within bounds
                            if 0 <= row < red.shape[0] and 0 <= col < red.shape[1]:
                                r = int(red[row, col])
                                g = int(green[row, col])
                                b = int(blue[row, col])
                                
                                # Only use color if not black (0,0,0)
                                if r > 0 or g > 0 or b > 0:
                                    color = (r, g, b)
                        except:
                            pass  # Keep default color on error
                    
                    filtered_results.append((g, v, poly, color))
            except:
                continue
        
        skipped = len(results) - len(filtered_results)
        print(f"   ✅ Filtered: {len(filtered_results):,} valid shapes (removed {skipped:,} tiny shapes)")
        
        if not filtered_results:
            progress.close()
            print(f"   ⚠️ No shapes large enough to import")
            QMessageBox.warning(
                app,
                "No Valid Shapes",
                f"All {len(results):,} shapes were too small.\n"
                f"Minimum area threshold: {min_area:.4f}\n\n"
                f"Try exporting with larger features or lower resolution."
            )
            return False
        
        if progress.wasCanceled():
            progress.close()
            return False
        
        # ============================================================
        # STEP 3: Limit maximum shapes for performance
        # ============================================================
        MAX_SHAPES = 10000  # Hard limit for UI performance
        
        if len(filtered_results) > MAX_SHAPES:
            print(f"   ⚠️ Too many shapes ({len(filtered_results):,}), limiting to {MAX_SHAPES:,}")
            
            # Sort by area (largest first) and keep top N
            filtered_results.sort(key=lambda x: x[2].area, reverse=True)
            filtered_results = filtered_results[:MAX_SHAPES]
            
            QMessageBox.information(
                app,
                "Large Dataset",
                f"Found {len(filtered_results):,} shapes after filtering.\n\n"
                f"Importing the largest {MAX_SHAPES:,} shapes for performance.\n\n"
                f"💡 Tip: For complete import, increase minimum area threshold."
            )
        
        progress.setValue(40)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 4: Process shapes with progress bar
        # ============================================================
        if not (hasattr(app, 'digitizer') and app.digitizer):
            progress.close()
            print(f"   ❌ No digitizer found")
            return False
        
        imported_count = 0
        failed_count = 0
        total = len(filtered_results)
        
        progress.setLabelText(f"Importing shapes...")
        progress.setMaximum(total)
        
        for idx, (geom, value, poly, color) in enumerate(filtered_results):
            if progress.wasCanceled():
                break
            
            # Update progress every 100 shapes
            if idx % 100 == 0:
                progress.setValue(idx)
                progress.setLabelText(f"Importing shapes: {idx:,}/{total:,}")
                QCoreApplication.processEvents()
            
            try:
                # Simplify complex polygons
                if poly.geom_type == 'Polygon':
                    coords = list(poly.exterior.coords)
                    
                    # Aggressive simplification for large polygons
                    if len(coords) > 100:
                        tolerance = min_area * 0.2  # 20% of minimum area
                        poly = poly.simplify(tolerance=tolerance, preserve_topology=True)
                        coords = list(poly.exterior.coords)
                    
                    drawing = {
                        'type': 'polygon',
                        'coordinates': [[float(x), float(y), 0.0] for x, y in coords[:-1]],
                        'color': color  # ✅ USE EXTRACTED RGB COLOR
                    }
                    
                    if app.digitizer.add_drawing_from_data(drawing):
                        imported_count += 1
                    else:
                        failed_count += 1
                
                elif poly.geom_type == 'MultiPolygon':
                    # Handle multipolygons
                    for sub_poly in poly.geoms:
                        if sub_poly.area < min_area:
                            continue
                        
                        coords = list(sub_poly.exterior.coords)
                        
                        # Simplify if needed
                        if len(coords) > 100:
                            tolerance = min_area * 0.2
                            sub_poly = sub_poly.simplify(tolerance=tolerance, preserve_topology=True)
                            coords = list(sub_poly.exterior.coords)
                        
                        drawing = {
                            'type': 'polygon',
                            'coordinates': [[float(x), float(y), 0.0] for x, y in coords[:-1]],
                            'color': color  # ✅ USE EXTRACTED RGB COLOR
                        }
                        
                        if app.digitizer.add_drawing_from_data(drawing):
                            imported_count += 1
                        else:
                            failed_count += 1
                
            except Exception as e:
                failed_count += 1
                continue
        
        # ============================================================
        # STEP 5: Final rendering
        # ============================================================
        progress.setLabelText(f"Rendering {imported_count:,} drawings...")
        progress.setValue(total)
        QCoreApplication.processEvents()
        
        print(f"   🎨 Rendering {imported_count:,} drawings...")
        if hasattr(app, 'vtk_widget') and app.vtk_widget:
            app.vtk_widget.GetRenderWindow().Render()
        
        progress.close()
        
        print(f"\n   ✅ Import Complete:")
        print(f"      - Imported: {imported_count:,}")
        if failed_count > 0:
            print(f"      - Failed: {failed_count:,}")
        print(f"{'='*60}\n")
        
        return imported_count > 0
        
    except ImportError as e:
        if 'progress' in locals():
            progress.close()
        print(f"   ❌ Missing library: {e}")
        print(f"   💡 Install: pip install rasterio shapely")
        return False
    except Exception as e:
        if 'progress' in locals():
            progress.close()
        print(f"   ❌ TIFF import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
def import_geotiff_as_texture(app, input_path: str) -> bool:
    """
    Import GeoTIFF as a textured surface overlay on the point cloud.
    Displays the actual RGB imagery, not vectorized shapes.
    """
    try:
        import rasterio
        import vtk
        from pathlib import Path
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt, QCoreApplication
        import numpy as np
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING GEOTIFF AS TEXTURED SURFACE")
        print(f"   Path: {input_path}")
        
        if not Path(input_path).exists():
            print(f"   ❌ File does not exist")
            return False
        
        # Progress dialog
        progress = QProgressDialog("Loading GeoTIFF texture...", "Cancel", 0, 100, app)
        progress.setWindowTitle("Import GeoTIFF")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(10)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 1: Read GeoTIFF with RGB bands
        # ============================================================
        with rasterio.open(input_path) as src:
            print(f"   📊 Raster: {src.width}x{src.height}")
            print(f"   📊 Bands: {src.count}")
            print(f"   🌍 CRS: {src.crs}")
            print(f"   📐 Bounds: {src.bounds}")
            
            # Read RGB bands
            if src.count >= 3:
                print(f"   🎨 Reading RGB bands...")
                red = src.read(1)
                green = src.read(2)
                blue = src.read(3)
            else:
                print(f"   ⚠️ Single-band image, converting to grayscale")
                gray = src.read(1)
                red = green = blue = gray
            
            # Get georeferencing info
            bounds = src.bounds
            transform = src.transform
            width = src.width
            height = src.height
        
        progress.setValue(30)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 2: Create VTK texture from RGB data
        # ============================================================
        print(f"   🎨 Creating VTK texture...")
        
        # Stack RGB into (height, width, 3) array
        rgb_array = np.stack([red, green, blue], axis=-1)
        
        # Flip vertically (VTK convention)
        rgb_array = np.flipud(rgb_array)
        
        # Convert to VTK image data
        vtk_image = vtk.vtkImageData()
        vtk_image.SetDimensions(width, height, 1)
        vtk_image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 3)
        
        # Copy data to VTK
        for y in range(height):
            for x in range(width):
                pixel = rgb_array[y, x]
                idx = (y * width + x) * 3
                vtk_image.GetPointData().GetScalars().SetTuple3(
                    y * width + x,
                    int(pixel[0]),
                    int(pixel[1]),
                    int(pixel[2])
                )
        
        progress.setValue(50)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 3: Create textured plane geometry
        # ============================================================
        print(f"   📐 Creating textured plane...")
        
        # Create plane with correct world coordinates
        plane = vtk.vtkPlaneSource()
        plane.SetOrigin(bounds.left, bounds.bottom, 0)
        plane.SetPoint1(bounds.right, bounds.bottom, 0)
        plane.SetPoint2(bounds.left, bounds.top, 0)
        plane.SetResolution(1, 1)  # Simple quad
        plane.Update()
        
        # Create texture
        texture = vtk.vtkTexture()
        texture.SetInputData(vtk_image)
        texture.InterpolateOn()
        texture.Update()
        
        progress.setValue(70)
        QCoreApplication.processEvents()
        
        # ============================================================
        # STEP 4: Create actor and add to scene
        # ============================================================
        print(f"   🎭 Adding to scene...")
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(plane.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetTexture(texture)
        
        # Make slightly transparent so point cloud shows through
        actor.GetProperty().SetOpacity(0.9)
        
        # Add to renderer
        if hasattr(app, 'vtk_widget') and app.vtk_widget:
            renderer = app.vtk_widget.GetRenderWindow().GetRenderers().GetFirstRenderer()
            renderer.AddActor(actor)
            
            # Store reference to actor so it can be removed later
            if not hasattr(app, 'geotiff_actors'):
                app.geotiff_actors = []
            app.geotiff_actors.append(actor)
            
            # Render
            app.vtk_widget.GetRenderWindow().Render()
            
            print(f"   ✅ GeoTIFF texture added successfully")
            print(f"   📏 Coverage: {bounds.left:.2f} to {bounds.right:.2f} (X)")
            print(f"              {bounds.bottom:.2f} to {bounds.top:.2f} (Y)")
        else:
            print(f"   ❌ No VTK widget found")
            progress.close()
            return False
        
        progress.setValue(100)
        progress.close()
        
        print(f"{'='*60}\n")
        return True
        
    except ImportError as e:
        if 'progress' in locals():
            progress.close()
        print(f"   ❌ Missing library: {e}")
        return False
    except Exception as e:
        if 'progress' in locals():
            progress.close()
        print(f"   ❌ GeoTIFF texture import failed: {e}")
        import traceback
        traceback.print_exc()
        return False    

def import_drawings_from_shapefile(app, input_path: str) -> bool:
    """Import drawings from Shapefile with proper rendering"""
    try:
        import geopandas as gpd
        from pathlib import Path
        
        print(f"\n{'='*60}")
        print(f"📥 IMPORTING DRAWINGS FROM SHAPEFILE")
        print(f"   Path: {input_path}")
        
        base_path = Path(input_path).with_suffix('')
        
        # Try to load all geometry types
        imported_count = 0
        
        for suffix in ['_points', '_lines', '_polygons', '']:
            try:
                shp_path = f"{base_path}{suffix}.shp"
                if not Path(shp_path).exists():
                    continue
                
                print(f"   📂 Loading: {shp_path}")
                gdf = gpd.read_file(shp_path)
                print(f"   📊 Found {len(gdf)} features")
                
                for idx, row in gdf.iterrows():
                    geom = row.geometry
                    
                    drawing = {
                        'color': (
                            int(row.get('color_r', 255)),
                            int(row.get('color_g', 255)),
                            int(row.get('color_b', 255))
                        ),
                        'text': str(row.get('text', '')),
                        'radius': float(row.get('radius', 0))
                    }
                    
                    if geom.geom_type == 'Point':
                        drawing['type'] = row.get('type', 'circle')
                        drawing['coordinates'] = [[geom.x, geom.y, 0]]
                    
                    elif geom.geom_type == 'LineString':
                        drawing['type'] = row.get('type', 'polyline')
                        drawing['coordinates'] = [
                            [x, y, 0] for x, y in geom.coords
                        ]
                    
                    elif geom.geom_type == 'Polygon':
                        drawing['type'] = row.get('type', 'polygon')
                        coords = list(geom.exterior.coords)[:-1]
                        drawing['coordinates'] = [
                            [x, y, 0] for x, y in coords
                        ]
                    
                    if hasattr(app, 'digitizer'):
                        # Use proper import method
                        if hasattr(app.digitizer, 'add_imported_drawing'):
                            app.digitizer.add_imported_drawing(drawing)
                        else:
                            app.digitizer.add_drawing_from_data(drawing)
                        imported_count += 1
                        print(f"   ✅ Added {drawing['type']} from import")
                        
            except Exception as e:
                print(f"   ⚠️ Could not load {suffix}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # CRITICAL: Force render update
        if imported_count > 0:
            print(f"\n   🎨 Updating display...")
            
            # Try multiple render methods
            if hasattr(app, 'vtk_widget') and app.vtk_widget:
                try:
                    app.vtk_widget.GetRenderWindow().Render()
                    print(f"   ✅ VTK render triggered")
                except:
                    pass
            
            # Try calling update method
            if hasattr(app, 'update_display'):
                try:
                    app.update_display()
                    print(f"   ✅ Display update called")
                except:
                    pass
            
            # Try refresh method
            if hasattr(app, 'refresh'):
                try:
                    app.refresh()
                    print(f"   ✅ Refresh called")
                except:
                    pass
            
            print(f"   ✅ Imported {imported_count} drawings")
        else:
            print(f"   ⚠️ No drawings imported")
        
        print(f"{'='*60}\n")
        
        return imported_count > 0
        
    except ImportError:
        print("   ⚠️ geopandas not installed")
        return False
    except Exception as e:
        print(f"   ❌ Shapefile import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
 