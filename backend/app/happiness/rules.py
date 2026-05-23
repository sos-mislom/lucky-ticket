from dataclasses import dataclass
import re

from pydantic import BaseModel, Field


class HappinessResult(BaseModel):
    ticket_number: str
    degree: int = Field(..., ge=0, le=5)
    points: int = Field(..., ge=0)
    label: str
    reasons: list[str]
    matched_rules: list[str]


@dataclass(frozen=True)
class CuratedNumber:
    label: str
    reason: str


@dataclass(frozen=True)
class FoldSide:
    initial_sum: int
    root: int
    steps: int
    description: str


CURATED_NUMBERS: dict[str, CuratedNumber] = {
    "0369": CuratedNumber("математическая красота", "арифметическая прогрессия 0, 3, 6, 9"),
    "0123": CuratedNumber("математическая красота", "возрастающая арифметическая прогрессия"),
    "1234": CuratedNumber("математическая красота", "возрастающая арифметическая прогрессия"),
    "0271": CuratedNumber("математическая пасхалка", "первые цифры числа e: 2.71"),
    "0314": CuratedNumber("математическая пасхалка", "первые цифры числа pi: 3.14"),
    "0618": CuratedNumber("математическая пасхалка", "первые цифры золотого сечения: 0.618"),
    "1618": CuratedNumber("математическая пасхалка", "первые цифры золотого сечения: 1.618"),
    "1984": CuratedNumber("культурная пасхалка", "узнаваемая отсылка к роману Оруэлла"),
    "2001": CuratedNumber("культурная пасхалка", "узнаваемая отсылка к космической классике"),
    "2048": CuratedNumber("цифровая пасхалка", "степень двойки и узнаваемая игра 2048"),
    "1729": CuratedNumber("математическая красота", "число Рамануджана-Харди"),
    "1337": CuratedNumber("культурная классика", "узнаваемая интернет-классика"),
}
CURATED_SHORT_NUMBERS: dict[str, CuratedNumber] = {
    "42": CuratedNumber("культурная классика", "ответ на главный вопрос жизни, Вселенной и всего такого"),
    "67": CuratedNumber("математическая пасхалка", "67 — lucky prime и свежая интернет-пасхалка"),
    "69": CuratedNumber("интернет-классика", "универсальный мемный номер"),
    "228": CuratedNumber("культурная пасхалка", "228 — узнаваемый русскоязычный интернет-мем"),
    "314": CuratedNumber("математическая пасхалка", "первые цифры числа pi: 3.14"),
    "420": CuratedNumber("интернет-классика", "420 — узнаваемый культурный код"),
    "666": CuratedNumber("культурная пасхалка", "узнаваемое число из массовой культуры"),
    "777": CuratedNumber("культурная пасхалка", "джекпотный счастливый номер"),
}
FIBONACCI_NUMBERS = {13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181, 6765}
POWER_OF_TWO_NUMBERS = {128, 256, 512, 1024, 2048, 4096, 8192}

LABELS = {
    0: "классический счастливый",
    1: "счастливый после свертки",
    2: "редкий счастливый",
    3: "счастливый после двойной свертки",
    4: "пасхалка",
    5: "обычный билет",
}

POINTS = {
    0: 1000,
    1: 700,
    2: 500,
    3: 350,
    4: 150,
    5: 1,
}


def score_ticket_number(value: str) -> HappinessResult:
    number = normalize_ticket_number(value)
    reasons: list[str] = []
    matched_rules: list[str] = []
    digits = [int(char) for char in number]

    if is_classic_lucky(digits):
        reasons.append("сумма левой половины сразу равна сумме правой")
        matched_rules.append("classic_lucky_sum")
        return build_result(number, 0, LABELS[0], reasons, matched_rules)

    folded = folded_lucky_match(digits)
    if folded is not None:
        left, right = folded
        max_steps = max(left.steps, right.steps)
        degree = 1 if max_steps == 1 else 3
        reasons.append(
            "суммы половинок сходятся после свертки цифр: "
            f"слева {left.description}, справа {right.description}"
        )
        matched_rules.append("digital_root_lucky_sum")
        return build_result(number, degree, LABELS[degree], reasons, matched_rules)

    curated = curated_number_match(number)
    if curated is not None:
        reasons.append(curated.reason)
        matched_rules.append("curated_number")
        return build_result(number, 4, curated.label, reasons, matched_rules)

    if is_palindrome(number):
        reasons.append("номер читается одинаково слева направо и справа налево")
        matched_rules.append("palindrome")
        return build_result(number, 4, LABELS[4], reasons, matched_rules)

    if is_arithmetic_progression(digits):
        reasons.append("цифры образуют арифметическую прогрессию")
        matched_rules.append("arithmetic_progression")
        return build_result(number, 4, LABELS[4], reasons, matched_rules)

    reasons.append("сильный счастливый узор не найден")
    matched_rules.append("baseline")
    return build_result(number, 5, LABELS[5], reasons, matched_rules)


def normalize_ticket_number(value: str) -> str:
    number = re.sub(r"\D", "", value)
    if not number:
        raise ValueError("ticket number must contain at least one digit")
    return number


def is_classic_lucky(digits: list[int]) -> bool:
    if len(digits) < 4 or len(digits) % 2 != 0:
        return False
    half = len(digits) // 2
    return sum(digits[:half]) == sum(digits[half:])


def folded_lucky_match(digits: list[int]) -> tuple[FoldSide, FoldSide] | None:
    if len(digits) < 4 or len(digits) % 2 != 0:
        return None
    half = len(digits) // 2
    left = fold_half(digits[:half])
    right = fold_half(digits[half:])
    if left.root != right.root:
        return None
    if max(left.steps, right.steps) == 0:
        return None
    return left, right


def fold_half(digits: list[int]) -> FoldSide:
    initial_sum = sum(digits)
    steps = 1 if len(digits) > 1 else 0
    description = format_initial_fold(digits, initial_sum)
    root, extra_steps, tail = fold_to_digit(initial_sum)
    steps += extra_steps
    if tail:
        description = f"{description} -> {tail}"
    return FoldSide(initial_sum=initial_sum, root=root, steps=steps, description=description)


def fold_to_digit(value: int) -> tuple[int, int, str]:
    steps = 0
    parts: list[str] = []
    while value >= 10:
        previous = value
        value = sum(int(char) for char in str(value))
        digits = " + ".join(str(char) for char in str(previous))
        parts.append(f"{digits} = {value}")
        steps += 1
    return value, steps, " -> ".join(parts)


def format_initial_fold(digits: list[int], value: int) -> str:
    if len(digits) <= 1:
        return str(value)
    return f"{' + '.join(str(digit) for digit in digits)} = {value}"


def format_fold(value: int, root: int) -> str:
    if value < 10:
        return str(value)
    digits = " + ".join(str(char) for char in str(value))
    return f"{value} -> {digits} = {root}"


def curated_number_match(number: str) -> CuratedNumber | None:
    if number in CURATED_NUMBERS:
        return CURATED_NUMBERS[number]

    stripped = number.lstrip("0")
    if stripped and number == stripped.zfill(len(number)) and stripped in CURATED_SHORT_NUMBERS:
        return CURATED_SHORT_NUMBERS[stripped]

    value = int(number)
    if number == str(value).zfill(len(number)):
        if value in FIBONACCI_NUMBERS:
            return CuratedNumber("математическая пасхалка", "число Фибоначчи")
        if value in POWER_OF_TWO_NUMBERS:
            return CuratedNumber("цифровая пасхалка", "степень двойки")

    return None


def is_palindrome(number: str) -> bool:
    return len(number) > 2 and number == number[::-1]


def is_arithmetic_progression(digits: list[int]) -> bool:
    if len(digits) < 3:
        return False
    step = digits[1] - digits[0]
    if step == 0:
        return False
    return all(digits[index] - digits[index - 1] == step for index in range(2, len(digits)))


def build_result(
    number: str,
    degree: int,
    label: str,
    reasons: list[str],
    matched_rules: list[str],
) -> HappinessResult:
    return HappinessResult(
        ticket_number=number,
        degree=degree,
        points=POINTS[degree],
        label=label,
        reasons=reasons,
        matched_rules=matched_rules,
    )
