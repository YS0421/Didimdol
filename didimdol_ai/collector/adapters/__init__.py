from .base import Adapter
from .boardes import KfeAdapter, KigamAdapter, KrissAdapter
from .kaeri import KaeriAdapter
from .kfri import KfriAdapter
from .kict import KictAdapter
from .kier import KierAdapter
from .kimm import KimmAdapter
from .kims import KimsAdapter
from .kiom import KiomAdapter
from .kist import KistAdapter
from .kribb import KribbAdapter
from .krri import KrriAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "kict": KictAdapter,
    "kist": KistAdapter,
    "kiom": KiomAdapter,
    "kribb": KribbAdapter,
    "kier": KierAdapter,
    "kriss": KrissAdapter,
    "kfe": KfeAdapter,
    "kigam": KigamAdapter,
    "kaeri": KaeriAdapter,
    "kimm": KimmAdapter,
    "kims": KimsAdapter,
    "krri": KrriAdapter,
    "kfri": KfriAdapter,
}
