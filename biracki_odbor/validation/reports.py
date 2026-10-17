"""Stable issue codes and Cyrillic message templates.

Keep codes here (single source of truth) so the GUI can map code →
icon/severity/help-text without scattering string literals.

Issue and ValidationReport themselves live in core.models so that core
modules can return them without importing the validation package.
"""

from __future__ import annotations

from biracki_odbor.core.models import Issue, ValidationReport  # re-export

__all__ = ["Issue", "ValidationReport", "Codes", "message"]


class Codes:
    # Pre-flight
    FILE_MISSING = "FILE_MISSING"
    FILE_LOCKED = "FILE_LOCKED"
    SHEET_MISSING = "SHEET_MISSING"
    HEADER_MISMATCH = "HEADER_MISMATCH"
    OIK_INCOMPLETE = "OIK_INCOMPLETE"
    ELECTION_INCOMPLETE = "ELECTION_INCOMPLETE"
    ELECTION_PLACEHOLDER = "ELECTION_PLACEHOLDER"
    PARTY_UNMATCHED = "PARTY_UNMATCHED"
    BM_UNKNOWN = "BM_UNKNOWN"
    EMPTY_BM = "EMPTY_BM"
    POPUNJENI_EMPTY = "POPUNJENI_EMPTY"
    NO_ALLOCATIONS = "NO_ALLOCATIONS"

    # Per-row
    JMBG_BAD_FORMAT = "JMBG_BAD_FORMAT"
    JMBG_BAD_CHECKSUM = "JMBG_BAD_CHECKSUM"
    JMBG_DUPLICATE = "JMBG_DUPLICATE"
    JMBG_GENDER_MISMATCH = "JMBG_GENDER_MISMATCH"
    NAME_EMPTY = "NAME_EMPTY"
    NAME_NON_CYRILLIC = "NAME_NON_CYRILLIC"
    NAME_AMBIGUOUS_SPLIT = "NAME_AMBIGUOUS_SPLIT"
    PHONE_TOO_SHORT = "PHONE_TOO_SHORT"
    ROW_OVERWRITE = "ROW_OVERWRITE"
    BM_NUMBER_NOT_INT = "BM_NUMBER_NOT_INT"
    FUNCTION_UNKNOWN = "FUNCTION_UNKNOWN"

    # Cross-party (Phase 2.5)
    PERSON_IN_MULTIPLE_PARTIES = "PERSON_IN_MULTIPLE_PARTIES"

    # Phase 2 import — file identity gating
    NO_MARKER = "NO_MARKER"
    WRONG_ELECTION = "WRONG_ELECTION"
    MARKER_ROW_MISMATCH = "MARKER_ROW_MISMATCH"
    STALE_GENERATION = "STALE_GENERATION"

    # Phase 2 popunjeni allowlist visibility
    UNIMPORTED_FILE = "UNIMPORTED_FILE"

    # Phase 2 — multiple submissions per party. Info-level: the
    # aggregator picked the latest by received_time_iso and ignored the
    # rest. Surfaced so the operator can see which file was actually
    # used. The accountability log shows the full submission history.
    MULTIPLE_SUBMISSIONS = "MULTIPLE_SUBMISSIONS"

    # Phase 1 — demo mode active. Info-level. Surfaced so the GUI
    # banner can show "Demo mode: ограничено на 1 бирачко место" with
    # the actual BM number echoed back.
    DEMO_MODE_LIMIT = "DEMO_MODE_LIMIT"

    # B1 — committee member's JMBG matches a candidate's JMBG in the
    # candidacies registry. A candidate cannot also serve on the
    # бирачки одбор (rule confirmed in plan §1.1). Hard reject.
    PERSON_IS_CANDIDATE = "PERSON_IS_CANDIDATE"

    # A committee member's JMBG already sits in a filled slot in the
    # OTHER workflow's master (стални vs проширени) -- one person can't
    # hold a seat in both compositions at once. Hard reject.
    PERSON_IN_OTHER_WORKFLOW = "PERSON_IN_OTHER_WORKFLOW"

    # B2 — member would not be ≥ 18 years old on election day. Hard
    # reject — committee service requires majority age across stalni
    # AND prošireni.
    PERSON_UNDER_18 = "PERSON_UNDER_18"

    # Phase 2 import — file safety pipeline
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TOO_SMALL = "FILE_TOO_SMALL"
    NOT_XLSX = "NOT_XLSX"
    MACROS_PRESENT = "MACROS_PRESENT"
    EMBEDDED_OBJECTS = "EMBEDDED_OBJECTS"
    SUSPICIOUS_COMPRESSION = "SUSPICIOUS_COMPRESSION"
    EXTERNAL_LINKS = "EXTERNAL_LINKS"


# Cyrillic message templates. Use .format(**ctx) to fill placeholders.
_MESSAGES: dict[str, str] = {
    Codes.FILE_MISSING: "Фајл не постоји: {file}",
    Codes.FILE_LOCKED: "Фајл се не може отворити (можда је отворен у Excel-у): {file}",
    Codes.SHEET_MISSING: "У фајлу '{file}' недостаје лист '{sheet}'",
    Codes.HEADER_MISMATCH: "У листу '{sheet}' недостаје колона '{detail}'",
    Codes.OIK_INCOMPLETE: "ОИК поставке нису потпуне: {detail}",
    Codes.ELECTION_INCOMPLETE: "Изборна конфигурација није потпуна: {detail}",
    Codes.ELECTION_PLACEHOLDER: "Изборна конфигурација садржи примерне вредности: {detail}",
    Codes.PARTY_UNMATCHED: (
        "Странка '{detail}' из збирне табеле није у листи 'party_full_names'."
        " Биће коришћен '_default'."
    ),
    Codes.BM_UNKNOWN: (
        "Бирачко место бр. {row} се не налази у ОИК поставкама — додајте га"
        " у Поставке или преконфигуришите шаблон"
    ),
    Codes.EMPTY_BM: "Бирачко место бр. {row} нема ниједног члана",
    Codes.POPUNJENI_EMPTY: "У директоријуму 'popunjeni' нема .xlsx фајлова",
    Codes.NO_ALLOCATIONS: "У листу 'Raspodela' нема ниједне расподеле по странкама",

    Codes.JMBG_BAD_FORMAT: "ЈМБГ '{detail}' нема 13 цифара",
    Codes.JMBG_BAD_CHECKSUM: "ЈМБГ '{detail}' не пролази MOD 11 проверу",
    Codes.JMBG_DUPLICATE: "ЈМБГ '{detail}' се појављује више пута",
    Codes.JMBG_GENDER_MISMATCH: (
        "ЈМБГ за '{detail}' указује на супротан пол од имена — проверите цифре"
        " или унос имена (могуће је да су име и презиме замењени)"
    ),
    Codes.NAME_EMPTY: "Име и презиме је празно",
    Codes.NAME_NON_CYRILLIC: "Име '{detail}' садржи знакове ван ћирилице",
    Codes.NAME_AMBIGUOUS_SPLIT: (
        "'{detail}' има више од две речи — није јасно шта је име а шта"
        " презиме. Ручно исправите у Корекцијама."
    ),
    Codes.PHONE_TOO_SHORT: "Број телефона '{detail}' има мање од 6 цифара",
    Codes.ROW_OVERWRITE: (
        "Слот (БМ {row}, {detail}) већ постоји у другом фајлу — претходни запис"
        " је преписан"
    ),
    Codes.BM_NUMBER_NOT_INT: "Поље 'БМ бр.' није цео број: '{detail}'",
    Codes.FUNCTION_UNKNOWN: "Непозната функција: '{detail}'",

    Codes.PERSON_IN_MULTIPLE_PARTIES: (
        "Особа са ЈМБГ '{detail}' је пријављена од стране више странака"
    ),

    # Import-time identity gating
    Codes.NO_MARKER: (
        "Фајл '{file}' нема идентитетску ознаку — није генерисан овим"
        " програмом. Поново покрените Фазу 1 и користите тако створене фајлове."
    ),
    Codes.WRONG_ELECTION: (
        "Фајл '{file}' припада другим изборима (ознака не одговара"
        " тренутној изборној конфигурацији)."
    ),
    Codes.MARKER_ROW_MISMATCH: (
        "Фајл '{file}' има ознаку странке '{detail}', али редови у фајлу"
        " припадају другој странци — могуће је да је заштита листа била"
        " пробијена и подаци мењани."
    ),
    Codes.STALE_GENERATION: (
        "Фајл '{file}' је генерисан у старој серији Фазе 1. Странка мора"
        " да поднесе нови образац генерисан после поништавања."
    ),

    # Visibility (Phase 2 aggregate sees files not imported through the button)
    Codes.UNIMPORTED_FILE: (
        'Фајл \'{file}\' није увезен кроз програм и биће занемарен.'
        ' Користите дугме „Увези фајлове…" да га учитате.'
    ),

    # Multiple submissions per party — info only.
    Codes.MULTIPLE_SUBMISSIONS: "{detail}",

    # Demo mode limit echo — info only.
    Codes.DEMO_MODE_LIMIT: (
        "Demo режим: ограничено на бирачко место бр. {row}."
        " Активирајте лиценцу за пуну функционалност."
    ),

    # B1 — committee/candidate cross-check.
    Codes.PERSON_IS_CANDIDATE: (
        "Особа са ЈМБГ '{detail}' је кандидат на овим изборима —"
        " не може истовремено бити члан бирачког одбора."
    ),

    # стални/проширени cross-check.
    Codes.PERSON_IN_OTHER_WORKFLOW: (
        "Особа са ЈМБГ '{detail}' је већ члан бирачког одбора у {other_workflow} —"
        " не може истовремено бити члан у оба састава."
    ),

    # B2 — age check.
    Codes.PERSON_UNDER_18: (
        "Особа са ЈМБГ '{detail}' није напунила 18 година до дана"
        " избора — не може бити члан бирачког одбора."
    ),

    # File safety
    Codes.FILE_TOO_LARGE: "Фајл '{file}' прелази дозвољених 10 МБ — одбачено.",
    Codes.FILE_TOO_SMALL: "Фајл '{file}' је сувише мали да би био исправан Excel фајл.",
    Codes.NOT_XLSX: "Фајл '{file}' није исправан .xlsx (zip) формат.",
    Codes.MACROS_PRESENT: (
        "Фајл '{file}' садржи макрое (VBA) — безбедносно одбачено."
    ),
    Codes.EMBEDDED_OBJECTS: (
        "Фајл '{file}' садржи угњеждене објекте (OLE) — безбедносно одбачено."
    ),
    Codes.SUSPICIOUS_COMPRESSION: (
        "Фајл '{file}' има сумњиво висок однос компресије (могуће zip-bomb)."
    ),
    Codes.EXTERNAL_LINKS: (
        "Фајл '{file}' садржи спољне везе ка другим радним свескама —"
        " безбедносно одбачено."
    ),
}


def message(code: str, **ctx: object) -> str:
    """Render a Cyrillic message for an issue code."""
    template = _MESSAGES.get(code, f"[{code}]")
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return template
