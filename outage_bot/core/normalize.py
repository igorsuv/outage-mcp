import re

_APOSTROPHES = str.maketrans({"’": "'", "`": "'", "ʼ": "'", "‘": "'", "´": "'"})
_LATIN_TO_CYR = str.maketrans("ABCEHIKMOPTX", "АВСЕНІКМОРТХ")
_LOOSE = str.maketrans({"є": "е", "э": "е", "і": "и", "ї": "и", "ы": "и", "'": None})
_STREET_TYPES = (
    r"вулиця|вул|улица|ул|проспект|просп|пр-т|пр|провулок|пров|переулок|пер|бульвар|бул|б-р|"
    r"площа|пл|наб|туп|ж/м|ж-м|мкр|кв-л"
)
_TYPE_RE = re.compile(rf"(?<![\w-])(?:{_STREET_TYPES})(?:\.|\s|$)\s*")


def street_key(name: str) -> str:
    """Ключ улицы без типа, регистра и порядка слов: 'просп. Яворницького Дмитра' == 'вул. Дмитра Яворницького',
    'Героїв-Рятувальників' == 'Героїв Рятувальників'."""
    s = name.lower().translate(_APOSTROPHES).replace("ё", "е")
    s = re.sub(r"\(.*?\)", " ", s)
    s = _TYPE_RE.sub(" ", s)
    s = re.sub(r"[^\w']", " ", s)
    return " ".join(sorted(s.split()))


def street_aliases(name: str) -> list[str]:
    """Ключи для названия и для старого названия в скобках: 'вул. Автоклубна (Виборзька)'."""
    keys = [street_key(name)]
    keys += [street_key(m) for m in re.findall(r"\((.*?)\)", name)]
    return [k for k in dict.fromkeys(keys) if k]


def loose_key(name: str) -> str:
    """street_key без различий укр/рус написания: 'Бєляєва' == 'Беляева'."""
    return street_key(name).translate(_LOOSE)


def search_token(name: str) -> str:
    return max(street_key(name).split() or [""], key=len)


def house_key(house: str) -> str:
    """'58/А', '58 а', '58a' -> '58А'; '8//1' -> '8/1'."""
    h = house.strip().upper().translate(_LATIN_TO_CYR).replace(" ", "")
    h = re.sub(r"/+", "/", h)
    return re.sub(r"(\d)/(?=[А-ЯІЇЄҐ]$)", r"\1", h)
