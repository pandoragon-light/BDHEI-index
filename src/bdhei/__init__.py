"""Calculate climate indices from station or gridded temperature and precipitation."""
from .climate import calculate_climate_from_config
from .station import calculate_station_from_config

__all__ = ["calculate_climate_from_config", "calculate_station_from_config"]
