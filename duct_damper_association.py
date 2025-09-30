# Import required modules
import math
from typing import Dict, List, Tuple, Any, Optional
from cks_client import CKSClientManager
from cks_sdk.models import FeatureType

# Constants
DEFAULT_DISTANCE_THRESHOLD = 13.0
DUCT_EXTENSION_UNITS = 13.0


class DuctDamperAssociation:
    """
    Class for associating dampers with ducts based on perpendicular distance calculations.
    Uses one-to-one mapping to ensure each duct can only be assigned to one damper.
    """
    
    def __init__(self, distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD):
        """
        Initialize the DuctDamperAssociation class.
        
        Args:
            distance_threshold: Maximum distance for damper-duct association
        """
        self.distance_threshold = distance_threshold
        self.cks_client = CKSClientManager.get_instance().client
    
    def point_to_line_distance(self, point: Tuple[float, float], line_start: Tuple[float, float], line_end: Tuple[float, float]) -> Tuple[float, str]:
        """
        Calculate the perpendicular distance from a point to a line segment with extensions.
        
        Args:
            point: (x, y) coordinates of the point
            line_start: (x, y) coordinates of line segment start
            line_end: (x, y) coordinates of line segment end
            
        Returns:
            Tuple of (distance, intersection_type) where intersection_type is:
            - "actual": perpendicular intersects the original line segment
            - "extended": perpendicular intersects the extended line segment (but not original)
            - "none": no intersection
        """
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end
        
        # Calculate the squared length of the line segment
        line_length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        
        if line_length_sq == 0:
            # Line segment is actually a point
            distance = math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
            return distance, "actual"
        
        # Calculate the parameter t for the closest point on the line
        t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_length_sq
        
        # Calculate line length for absolute extension
        line_length = math.sqrt(line_length_sq)
        extension_ratio = DUCT_EXTENSION_UNITS / line_length  # Extension units as ratio of line length
        
        # Check intersection types
        if 0 <= t <= 1:
            # Perpendicular intersects the original line segment
            closest_x = x1 + t * (x2 - x1)
            closest_y = y1 + t * (y2 - y1)
            distance = math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)
            return distance, "actual"
        elif -extension_ratio <= t <= 1 + extension_ratio:
            # Perpendicular intersects the extended line segment (DUCT_EXTENSION_UNITS extension on each side)
            closest_x = x1 + t * (x2 - x1)
            closest_y = y1 + t * (y2 - y1)
            distance = math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)
            return distance, "extended"
        else:
            # No intersection with extended segment
            dist_to_start = math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
            dist_to_end = math.sqrt((px - x2) ** 2 + (py - y2) ** 2)
            distance = min(dist_to_start, dist_to_end)
            return distance, "none"
    
    def extract_damper_coordinates(self, dampers: List[Any]) -> List[Tuple[str, Tuple[float, float]]]:
        """
        Extract damper ID and coordinates from dampers data.
        
        Args:
            dampers: List of damper objects from CKS
            
        Returns:
            List of tuples (damper_id, (x, y) coordinates)
        """
        damper_coords = []
        
        for damper in dampers:
            damper_id = getattr(damper, 'id', 'unknown')
            coordinates = None
            
            if hasattr(damper, 'final_geojson') and damper.final_geojson:
                geojson = damper.final_geojson
                if hasattr(geojson, 'features') and geojson.features:
                    coords = geojson.features[0].geometry.coordinates
                    if len(coords) >= 2:
                        coordinates = (float(coords[0]), float(coords[1]))
            
            if coordinates:
                damper_coords.append((damper_id, coordinates))
        
        return damper_coords
    
    def extract_duct_coordinates(self, ducts: List[Any]) -> List[Tuple[str, List[Tuple[float, float]]]]:
        """
        Extract duct ID and line coordinates from ducts data.
        
        Args:
            ducts: List of duct objects from CKS
            
        Returns:
            List of tuples (duct_id, list of (x, y) coordinates forming the line)
        """
        duct_coords = []
        
        for duct in ducts:
            duct_id = getattr(duct, 'id', 'unknown')
            coordinates = []
            
            if hasattr(duct, 'final_geojson') and duct.final_geojson:
                geojson = duct.final_geojson
                if isinstance(geojson, dict) and 'features' in geojson:
                    feature = geojson['features'][0]
                    if 'geometry' in feature and 'coordinates' in feature['geometry']:
                        coords = feature['geometry']['coordinates']
                        if len(coords) >= 2:
                            coordinates = [(float(coord[0]), float(coord[1])) for coord in coords]
            
            if coordinates:
                duct_coords.append((duct_id, coordinates))
        
        return duct_coords
    
    def map_dampers_to_ducts(self, damper_coords: List[Tuple[str, Tuple[float, float]]], 
                            duct_coords: List[Tuple[str, List[Tuple[float, float]]]]) -> Dict[str, str]:
        """
        Map each damper to the closest duct based on perpendicular distance using one-to-one mapping.
        Prioritizes actual intersections over extended intersections.
        Uses greedy assignment to ensure each duct can only be assigned to one damper.
        
        Args:
            damper_coords: List of (damper_id, (x, y)) tuples
            duct_coords: List of (duct_id, list of (x, y)) tuples
            
        Returns:
            Dictionary mapping damper_id to duct_id (or 'NA' if no association)
        """
        # Build all candidate pairs with intersection type and distance
        candidate_pairs: List[Tuple[str, float, int, int]] = []  # (intersection_type, distance, damper_idx, duct_idx)
        
        for d_idx, (damper_id, damper_point) in enumerate(damper_coords):
            for duct_idx, (duct_id, duct_line_coords) in enumerate(duct_coords):
                # Calculate distance to each line segment in the duct
                min_distance = float('inf')
                best_intersection_type = "none"
                
                for i in range(len(duct_line_coords) - 1):
                    line_start = duct_line_coords[i]
                    line_end = duct_line_coords[i + 1]
                    
                    distance, intersection_type = self.point_to_line_distance(damper_point, line_start, line_end)
                    
                    # Only consider if there's an intersection and distance is better
                    if intersection_type != "none" and distance < min_distance:
                        min_distance = distance
                        best_intersection_type = intersection_type
                
                # Add to candidates if within threshold and has intersection
                if best_intersection_type != "none" and min_distance <= self.distance_threshold:
                    candidate_pairs.append((best_intersection_type, min_distance, d_idx, duct_idx))
        
        # Sort by intersection type priority (actual first, then extended), then by distance
        def sort_key(t):
            intersection_type, distance, _, _ = t
            # Priority: actual=0, extended=1 (so actual comes first)
            type_priority = 0 if intersection_type == "actual" else 1
            return (type_priority, distance)
        
        candidate_pairs.sort(key=sort_key)
        print(candidate_pairs)
        
        # Track which ducts have been used
        duct_used: List[bool] = [False] * len(duct_coords)
        
        # Initialize mapping - all dampers start as unmapped
        damper_to_duct_mapping = {damper_id: 'NA' for damper_id, _ in damper_coords}
        
        # Iterate through sorted pairs and assign if duct is available
        for _, _, damper_idx, duct_idx in candidate_pairs:
            if duct_used[duct_idx]:
                continue  # This duct is already assigned to another damper
            
            # Assign this damper to the duct
            damper_id = damper_coords[damper_idx][0]
            duct_id = duct_coords[duct_idx][0]
            damper_to_duct_mapping[damper_id] = duct_id
            duct_used[duct_idx] = True
        
        return damper_to_duct_mapping
    
    def retrieve_data_from_cks(self, worksheet_id: str) -> Tuple[List[Any], List[Any]]:
        """
        Retrieve ducts and dampers data from CKS.
        
        Args:
            worksheet_id: ID of the worksheet to retrieve data from
            
        Returns:
            Tuple of (ducts, dampers) lists
            
        Raises:
            Exception: If data retrieval fails
        """
        try:
            # Get ducts from CKS
            ducts = self.cks_client.ducts_fittings.get_ducts_by_worksheet(worksheet_id)
            
            # Get dampers from CKS
            saved_output = self.cks_client.points.get_point_features(worksheet_id, type=FeatureType.DAMPER)
            
            # Handle both list and PointsGenerationOutput formats
            if hasattr(saved_output, 'data') and 'results' in saved_output.data:
                dampers = saved_output.data['results']
            elif isinstance(saved_output, list):
                dampers = saved_output
            else:
                dampers = []
            
            return ducts, dampers
        except Exception as e:
            raise Exception(f"Failed to retrieve data from CKS: {str(e)}")
    
    def process_worksheet(self, worksheet_id: str) -> Dict[str, str]:
        """
        Process a worksheet to generate damper-to-duct mapping.
        
        Args:
            worksheet_id: ID of the worksheet to process
            
        Returns:
            Dictionary mapping damper_id to duct_id
            
        Raises:
            Exception: If processing fails
        """
        try:
            # Retrieve data from CKS
            ducts, dampers = self.retrieve_data_from_cks(worksheet_id)
            
            # Extract coordinates
            damper_coords = self.extract_damper_coordinates(dampers)
            duct_coords = self.extract_duct_coordinates(ducts)
            
            # Perform mapping
            damper_duct_mapping = self.map_dampers_to_ducts(damper_coords, duct_coords)
            
            return damper_duct_mapping
            
        except Exception as e:
            raise Exception(f"Failed to process worksheet {worksheet_id}: {str(e)}")


def main():
    """
    Main function to demonstrate the DuctDamperAssociation class usage.
    """
    # Set worksheet_id (you may need to adjust this)
    worksheet_id = "6371abad-c847-4117-8fe9-446edc0261ec"
    
    # Initialize the DuctDamperAssociation class
    association = DuctDamperAssociation(distance_threshold=DEFAULT_DISTANCE_THRESHOLD)
    
    # Process the worksheet
    try:
        damper_duct_mapping = association.process_worksheet(worksheet_id)
        #remove this later(just for testing)
        print("_________________________")
        print("damper_duct_mapping:")
        print(damper_duct_mapping)
        
        return damper_duct_mapping
    except Exception as e:
        return {}


if __name__ == "__main__":
    main()
