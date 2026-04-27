"""GNSS data utilities"""
import math

class GNSSValidator:
    """Validate and process GNSS NavSatFix data"""

    @staticmethod
    def is_valid(lat, lon, alt=None):
        """Check if latitude/longitude are valid"""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            return math.isfinite(lat_f) and math.isfinite(lon_f) and lat_f != 0.0 and lon_f != 0.0
        except Exception:
            return False

    @staticmethod
    def format_position(lat, lon, alt=None, status=-1):
        """Format position data for display with status info"""
        status_map = {
            -1: "❌ 无信号 - 请移至户外",
            0: "✓ GPS 定位",
            1: "✓ DGPS 定位",
            2: "✓ PPS 定位",
            4: "✓✓ RTK 固定 (厘米级)",
            5: "✓✓ RTK 浮点 (分米级)",
        }
        status_text = status_map.get(status, f"? 未知信号 ({status})")

        if not GNSSValidator.is_valid(lat, lon):
            return f"{status_text} - 等待有效坐标"

        alt_str = f", Alt: {float(alt):.2f}m" if alt is not None else ""
        return f"{status_text} - Lat: {float(lat):.6f}, Lon: {float(lon):.6f}{alt_str}"


__all__ = ['GNSSValidator']
