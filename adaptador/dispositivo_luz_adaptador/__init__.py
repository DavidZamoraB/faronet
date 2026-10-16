"""DispositivoLuzAdaptador: biblioteca de comunicacion entre el nodo y el Faro."""
from .adaptador import (DispositivoLuzAdaptador, Estadisticas, ErrorFaro, InfoFaro,
                        InfoFirmware, ResultadoTx, TramaRecibida)
from .trama import (DIFUSION, MAX_CARGA, MAX_TRAMA, Trama, ErrorTrama,
                    formatear_direccion, parsear_direccion)

__version__ = "1.0.0"
__all__ = [
    "DispositivoLuzAdaptador", "Estadisticas", "ErrorFaro", "InfoFaro", "InfoFirmware",
    "ResultadoTx", "TramaRecibida", "Trama", "ErrorTrama", "DIFUSION", "MAX_CARGA",
    "MAX_TRAMA", "formatear_direccion", "parsear_direccion",
]
