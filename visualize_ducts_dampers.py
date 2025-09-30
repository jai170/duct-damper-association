import cv2
import numpy as np
import json

# Import required modules
from cks_client import CKSClientManager
from cks_sdk.models import FeatureType
from activities.helpers import load_image_data

# Initialize CKS client
cks_v2 = CKSClientManager.get_instance().client

# Set worksheet_id
worksheet_id = "6371abad-c847-4117-8fe9-446edc0261ec"

print("Fetching worksheet image...")
# Get image for visualization
zoom_factor = 2
image_data = cks_v2.worksheets.get_image_by_zoom(worksheet_id, zoom=zoom_factor, bg_removal=False)
image_bytes = load_image_data(image_data)
image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)

# Get scale factors from worksheet metadata
print("Getting worksheet metadata for scale factors...")
meta_data = cks_v2.worksheets.get_worksheet_meta(worksheet_id)
page_width = meta_data["page_width"]
page_height = meta_data["page_height"]
fe_width = meta_data["fe_width"]
fe_height = meta_data["fe_height"]

scale_factor_x = page_width / fe_width
scale_factor_y = page_height / fe_height

print(f"Scale factors - X: {scale_factor_x}, Y: {scale_factor_y}")
print(f"Zoom factor: {zoom_factor}")

# Create a copy for drawing
image_with_overlay = image.copy()

print("Retrieving ducts from CKS...")
# Get ducts from CKS
unnamed_duct_in_cks = cks_v2.ducts_fittings.get_ducts_by_worksheet(worksheet_id)
print(f"Retrieved {len(unnamed_duct_in_cks)} ducts")

print("Retrieving dampers from CKS...")
# Get dampers from CKS
saved_output = cks_v2.points.get_point_features(worksheet_id, type=FeatureType.DAMPER)

# Handle both list and PointsGenerationOutput formats
if hasattr(saved_output, 'data') and 'results' in saved_output.data:
    saved_dampers = saved_output.data['results']
elif isinstance(saved_output, list):
    saved_dampers = saved_output
else:
    saved_dampers = []

print(f"Retrieved {len(saved_dampers)} dampers")

# Draw ducts as lines
print("Drawing ducts...")
for i, duct in enumerate(unnamed_duct_in_cks):
    if hasattr(duct, 'final_geojson') and duct.final_geojson:
        geojson = duct.final_geojson
        if 'features' in geojson and geojson['features']:
            feature = geojson['features'][0]
            if 'geometry' in feature and 'coordinates' in feature['geometry']:
                coords = feature['geometry']['coordinates']
                if len(coords) >= 2:
                    # Convert coordinates to image space by multiplying by scale factors and zoom factor
                    points = []
                    for coord in coords:
                        # Convert from PDF coordinates to image coordinates
                        x = int(coord[0] * scale_factor_x * zoom_factor)
                        y = int(coord[1] * scale_factor_y * zoom_factor * -1)  # Flip Y axis
                        points.append((x, y))
                    
                    # Draw line
                    if len(points) >= 2:
                        cv2.polylines(image_with_overlay, [np.array(points)], False, (255, 0, 0), 2)  # Blue lines

# Draw dampers as points
print("Drawing dampers...")
for i, damper in enumerate(saved_dampers):
    if hasattr(damper, 'final_geojson') and damper.final_geojson:
        geojson = damper.final_geojson
        if hasattr(geojson, 'features') and geojson.features:
            feature = geojson.features[0]
            if hasattr(feature.geometry, 'coordinates'):
                coords = feature.geometry.coordinates
                if len(coords) >= 2:
                    # Convert from PDF coordinates to image coordinates
                    x = int(coords[0] * scale_factor_x * zoom_factor)
                    y = int(coords[1] * scale_factor_y * zoom_factor * -1)  # Flip Y axis
                    
                    # Get damper type for color coding
                    damper_type = getattr(damper, 'type', 'Unknown')
                    confidence = getattr(damper, 'confidence', 0)
                    damper_id = getattr(damper, 'id', f'D{i}')
                    
                    # Color code by type (BGR format for OpenCV)
                    if damper_type == 'CRD':
                        color = (0, 0, 255)  # Red
                        radius = 8
                    elif damper_type == 'MVD':
                        color = (0, 255, 0)  # Green
                        radius = 10
                    else:
                        color = (0, 165, 255)  # Orange
                        radius = 6
                    
                    # Draw circle
                    cv2.circle(image_with_overlay, (x, y), radius, color, -1)
                    cv2.circle(image_with_overlay, (x, y), radius, (0, 0, 0), 2)  # Black border
                    
                    # Add text label
                    label = f"{damper_id}:{damper_type}"
                    cv2.putText(image_with_overlay, label, (x + 10, y - 10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    cv2.putText(image_with_overlay, f"{confidence:.2f}", (x + 10, y + 5), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

# Add title
cv2.putText(image_with_overlay, f"Ducts (Blue) and Dampers - Worksheet: {worksheet_id}", 
           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

# Save the image in the duct_damper_association folder
import os
output_dir = os.path.dirname(os.path.abspath(__file__))  # Get the directory of this script
output_path = os.path.join(output_dir, f'ducts_dampers_visualization_{worksheet_id}.jpg')
cv2.imwrite(output_path, image_with_overlay)
print(f"Visualization saved as: {output_path}")

# Also save a smaller version for easier viewing
height, width = image_with_overlay.shape[:2]
scale_factor = 0.5
new_width = int(width * scale_factor)
new_height = int(height * scale_factor)
resized_image = cv2.resize(image_with_overlay, (new_width, new_height))
small_output_path = os.path.join(output_dir, f'ducts_dampers_visualization_{worksheet_id}_small.jpg')
cv2.imwrite(small_output_path, resized_image)
print(f"Small version saved as: {small_output_path}")

print(f"\nSummary:")
print(f"- {len(unnamed_duct_in_cks)} ducts plotted as blue lines")
print(f"- {len(saved_dampers)} dampers plotted as colored points")
print(f"- Red circles: CRD dampers")
print(f"- Green squares: MVD dampers")
print(f"- Point size indicates confidence level")