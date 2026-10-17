"""Serbian eID card reader — a `ctypes` wrapper around the official MUP
"Čelik API" DLL.

Consolidated from the most complete of five near-duplicate copies in
`Celik/` (`Celik/Instaler/serbian_id_reader.py`) into the one canonical
module this app uses. Struct layouts and function signatures are
correct, hard-won integration work confirmed against `Celik/CelikApi.h`
— kept as-is. Fixed here, relative to every prior copy:

  - DLL path resolution: tries a bundled copy first, then the official
    system install location — every prior copy hardcoded the system
    path only, so it failed on any machine without a separate MUP
    middleware install even though a copy of the DLL sat right next to
    the script.
  - Error codes are mapped to the specific EID_E_* constants from
    CelikApi.h instead of one generic "greška [code]" message, so the
    operator can tell "no card inserted" from "wrong card" from
    "reader not found."
  - The portrait (EID_PORTRAIT) is actually surfaced on the returned
    dict — every prior copy read it into a struct and then discarded
    it.

get_reader_name() still always returns b"" (no real multi-reader
enumeration) — inherited from every prior copy; the DLL presumably
supports it, but implementing real enumeration needs testing against
actual multi-reader hardware this session doesn't have. Flagged, not
silently carried forward as if it were solved.
"""

from __future__ import annotations

import os
import sys
from ctypes import POINTER, Structure, byref, c_char, c_int, c_ubyte
from datetime import datetime
from pathlib import Path

from formalizator.core.models import VoterEntry

# `ctypes.windll` / `ctypes.wintypes` only exist on Windows — guarded
# the same way `biracki_odbor.integrations.outlook` guards pywin32, so
# this module still imports cleanly on non-Windows dev/CI machines and
# GUI code can check EID_READER_AVAILABLE instead of hard-failing.
EID_READER_AVAILABLE: bool = False
_IMPORT_ERR: str = ""
try:  # pragma: no cover — covered by a smoke test where reachable
    if sys.platform == "win32":
        from ctypes import windll  # noqa: F401
        from ctypes.wintypes import LPCSTR
        EID_READER_AVAILABLE = True
    else:
        LPCSTR = None  # type: ignore[assignment]
except Exception as e:  # noqa: BLE001 — any import error means "no reader"
    _IMPORT_ERR = str(e)
    LPCSTR = None  # type: ignore[assignment]


class EidReaderUnavailable(Exception):
    """Raised when SerbianIDReader is constructed on a platform without
    ctypes.windll (i.e. not Windows). Callers should guard with
    EID_READER_AVAILABLE first and offer the manual-entry form instead."""

# Default system install location for the official MUP middleware —
# tried only as a fallback, after the bundled copy.
_SYSTEM_DLL_PATH = r"C:\Program Files\MUP RS\Celik\CelikApi.dll"

_ERROR_MESSAGES: dict[int, str] = {
    -1: "Општа грешка читача.",
    -2: "Неисправан параметар.",
    -3: "Верзија API-ја није подржана.",
    -4: "API није иницијализован.",
    -5: "Радња се не може извршити.",
    -6: "Грешка читача картица — провери да је читач прикључен.",
    -7: "Картица није убачена.",
    -8: "Непозната картица.",
    -9: "Картица не одговара очекиваном типу.",
    -10: "Не могу да отворим сесију читања.",
    -11: "Подаци недостају на картици.",
    -12: "Провера безбедносног формата картице није успела.",
    -13: "Провера сертификата није успела.",
    -14: "Неисправна лозинка.",
    -15: "PIN је закључан.",
}


class EidReaderError(Exception):
    def __init__(self, code: int, context: str) -> None:
        self.code = code
        self.context = context
        msg = _ERROR_MESSAGES.get(code, f"Непозната грешка ({code}).")
        super().__init__(f"{context}: {msg}")


class EID_DOCUMENT_DATA(Structure):
    _pack_ = 4
    _fields_ = [
        ("docRegNo", c_char * 9), ("docRegNoSize", c_int),
        ("documentType", c_char * 2), ("documentTypeSize", c_int),
        ("issuingDate", c_char * 10), ("issuingDateSize", c_int),
        ("expiryDate", c_char * 10), ("expiryDateSize", c_int),
        ("issuingAuthority", c_char * 100), ("issuingAuthoritySize", c_int),
        ("documentSerialNumber", c_char * 10), ("documentSerialNumberSize", c_int),
        ("chipSerialNumber", c_char * 14), ("chipSerialNumberSize", c_int),
        ("documentName", c_char * 100), ("documentNameSize", c_int),
    ]


class EID_FIXED_PERSONAL_DATA(Structure):
    _pack_ = 4
    _fields_ = [
        ("personalNumber", c_char * 13), ("personalNumberSize", c_int),
        ("surname", c_char * 200), ("surnameSize", c_int),
        ("givenName", c_char * 200), ("givenNameSize", c_int),
        ("parentGivenName", c_char * 200), ("parentGivenNameSize", c_int),
        ("sex", c_char * 2), ("sexSize", c_int),
        ("placeOfBirth", c_char * 200), ("placeOfBirthSize", c_int),
        ("stateOfBirth", c_char * 200), ("stateOfBirthSize", c_int),
        ("dateOfBirth", c_char * 10), ("dateOfBirthSize", c_int),
        ("communityOfBirth", c_char * 200), ("communityOfBirthSize", c_int),
        ("statusOfForeigner", c_char * 200), ("statusOfForeignerSize", c_int),
        ("nationalityFull", c_char * 200), ("nationalityFullSize", c_int),
        ("purposeOfStay", c_char * 200), ("purposeOfStaySize", c_int),
        ("eNote", c_char * 200), ("eNoteSize", c_int),
    ]


class EID_VARIABLE_PERSONAL_DATA(Structure):
    _pack_ = 4
    _fields_ = [
        ("state", c_char * 100), ("stateSize", c_int),
        ("community", c_char * 200), ("communitySize", c_int),
        ("place", c_char * 200), ("placeSize", c_int),
        ("street", c_char * 200), ("streetSize", c_int),
        ("houseNumber", c_char * 20), ("houseNumberSize", c_int),
        ("houseLetter", c_char * 8), ("houseLetterSize", c_int),
        ("entrance", c_char * 10), ("entranceSize", c_int),
        ("floor", c_char * 6), ("floorSize", c_int),
        ("apartmentNumber", c_char * 12), ("apartmentNumberSize", c_int),
        ("addressDate", c_char * 10), ("addressDateSize", c_int),
        ("addressLabel", c_char * 60), ("addressLabelSize", c_int),
    ]


class EID_PORTRAIT(Structure):
    _pack_ = 4
    _fields_ = [
        ("portrait", c_ubyte * 7700),
        ("portraitSize", c_int),
    ]


def _resolve_dll_path(explicit_path: Path | str | None = None) -> Path:
    if explicit_path is not None:
        p = Path(explicit_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"CelikApi.dll није пронађен на: {p}")

    bundled = Path(__file__).resolve().parent.parent / "resources" / "CelikApi.dll"
    if bundled.exists():
        return bundled

    system = Path(_SYSTEM_DLL_PATH)
    if system.exists():
        return system

    raise FileNotFoundError(
        "CelikApi.dll није пронађен ни у инсталацији апликације ни на"
        f" системској путањи ({_SYSTEM_DLL_PATH})."
    )


class SerbianIDReader:
    """Wrapper for the official Čelik API DLL."""

    def __init__(self, dll_path: Path | str | None = None) -> None:
        if not EID_READER_AVAILABLE:
            raise EidReaderUnavailable(
                f"eID reader unavailable on this platform: {_IMPORT_ERR or 'not Windows'}"
            )
        from ctypes import windll
        resolved = _resolve_dll_path(dll_path)
        dll_dir = str(resolved.parent)
        os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        self.dll = windll.LoadLibrary(str(resolved))
        self._setup_functions()

    def _setup_functions(self) -> None:
        self.dll.EidStartup.argtypes = [c_int]
        self.dll.EidStartup.restype = c_int
        self.dll.EidCleanup.argtypes = []
        self.dll.EidCleanup.restype = c_int
        self.dll.EidBeginRead.argtypes = [LPCSTR, POINTER(c_int)]
        self.dll.EidBeginRead.restype = c_int
        self.dll.EidEndRead.argtypes = []
        self.dll.EidEndRead.restype = c_int
        self.dll.EidReadDocumentData.argtypes = [POINTER(EID_DOCUMENT_DATA)]
        self.dll.EidReadDocumentData.restype = c_int
        self.dll.EidReadFixedPersonalData.argtypes = [POINTER(EID_FIXED_PERSONAL_DATA)]
        self.dll.EidReadFixedPersonalData.restype = c_int
        self.dll.EidReadVariablePersonalData.argtypes = [POINTER(EID_VARIABLE_PERSONAL_DATA)]
        self.dll.EidReadVariablePersonalData.restype = c_int
        self.dll.EidReadPortrait.argtypes = [POINTER(EID_PORTRAIT)]
        self.dll.EidReadPortrait.restype = c_int

    def startup(self) -> None:
        result = self.dll.EidStartup(4)
        if result != 0:
            raise EidReaderError(result, "Покретање API-ја")

    def cleanup(self) -> None:
        self.dll.EidCleanup()

    def get_reader_name(self) -> bytes:
        return b""

    def read_card(self) -> VoterEntry:
        card_type = c_int()
        result = self.dll.EidBeginRead(self.get_reader_name(), byref(card_type))
        if result != 0:
            raise EidReaderError(result, "Отварање сесије читања")

        try:
            doc_data = EID_DOCUMENT_DATA()
            result = self.dll.EidReadDocumentData(byref(doc_data))
            if result != 0:
                raise EidReaderError(result, "Читање података о документу")

            fixed_data = EID_FIXED_PERSONAL_DATA()
            result = self.dll.EidReadFixedPersonalData(byref(fixed_data))
            if result != 0:
                raise EidReaderError(result, "Читање личних података")

            var_data = EID_VARIABLE_PERSONAL_DATA()
            result = self.dll.EidReadVariablePersonalData(byref(var_data))
            if result != 0:
                raise EidReaderError(result, "Читање адресе")

            portrait = EID_PORTRAIT()
            result = self.dll.EidReadPortrait(byref(portrait))
            portrait_jpeg: bytes | None = None
            if result == 0 and portrait.portraitSize > 0:
                portrait_jpeg = bytes(portrait.portrait[: portrait.portraitSize])

            def _s(buf: bytes, size: int) -> str:
                return buf[:size].decode("utf-8", errors="replace")

            street = _s(var_data.street, var_data.streetSize)
            house_number = _s(var_data.houseNumber, var_data.houseNumberSize)
            house_letter = _s(var_data.houseLetter, var_data.houseLetterSize)
            entrance = _s(var_data.entrance, var_data.entranceSize)
            floor = _s(var_data.floor, var_data.floorSize)
            apartment_number = _s(var_data.apartmentNumber, var_data.apartmentNumberSize)

            address = " ".join(filter(None, [street, house_number, house_letter]))
            apt_parts = []
            if entrance:
                apt_parts.append(f"улаз {entrance}")
            if floor:
                apt_parts.append(f"спрат {floor}")
            if apartment_number:
                apt_parts.append(f"стан {apartment_number}")
            if apt_parts:
                address += ", " + ", ".join(apt_parts)

            return VoterEntry(
                given_name=_s(fixed_data.givenName, fixed_data.givenNameSize),
                surname=_s(fixed_data.surname, fixed_data.surnameSize),
                jmbg=_s(fixed_data.personalNumber, fixed_data.personalNumberSize),
                date_of_birth=_s(fixed_data.dateOfBirth, fixed_data.dateOfBirthSize),
                city=_s(var_data.place, var_data.placeSize),
                full_address=address,
                document_reg_no=_s(doc_data.docRegNo, doc_data.docRegNoSize),
                date_of_issue=_s(doc_data.issuingDate, doc_data.issuingDateSize),
                issuing_authority=_s(doc_data.issuingAuthority, doc_data.issuingAuthoritySize),
                portrait_jpeg=portrait_jpeg,
                source="card",
            )
        finally:
            self.dll.EidEndRead()


def date_placeholders(now: datetime | None = None) -> dict[str, str]:
    """Dynamic date placeholders for declaration templates — same set
    `Instaler/serbian_id_reader.py` added (today/today_short/
    current_year/month/day/current_time/timestamp)."""
    now = now or datetime.now()
    return {
        "today": now.strftime("%d.%m.%Y."),
        "today_short": now.strftime("%d.%m."),
        "current_year": now.strftime("%Y."),
        "current_month": now.strftime("%m."),
        "current_day": now.strftime("%d."),
        "current_time": now.strftime("%H:%M"),
        "timestamp": now.strftime("%d.%m.%Y. %H:%M:%S"),
    }
