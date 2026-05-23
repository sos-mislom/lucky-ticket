from app.happiness.rules import score_ticket_number


def test_classic_lucky_is_class_zero_with_max_points() -> None:
    result = score_ticket_number("0101")

    assert result.degree == 0
    assert result.points == 1000
    assert result.label == "классический счастливый"
    assert "classic_lucky_sum" in result.matched_rules


def test_right_double_fold_lucky_is_third_class() -> None:
    result = score_ticket_number("0889")

    assert result.degree == 3
    assert result.points == 350
    assert result.label == "счастливый после двойной свертки"
    assert result.reasons == [
        "суммы половинок сходятся после свертки цифр: слева 0 + 8 = 8, справа 8 + 9 = 17 -> 1 + 7 = 8"
    ]
    assert "digital_root_lucky_sum" in result.matched_rules


def test_curated_numbers_are_fourth_class_easter_eggs() -> None:
    result = score_ticket_number("0369")

    assert result.degree == 4
    assert result.points == 150
    assert result.label == "математическая красота"
    assert result.reasons == ["арифметическая прогрессия 0, 3, 6, 9"]


def test_short_cultural_numbers_with_leading_zeroes_are_fourth_class() -> None:
    assert score_ticket_number("0228").degree == 4
    assert score_ticket_number("0228").label == "культурная пасхалка"
    assert score_ticket_number("0067").degree == 4
    assert score_ticket_number("0067").reasons == ["67 — lucky prime и свежая интернет-пасхалка"]


def test_math_sequences_are_fourth_class_easter_eggs() -> None:
    fibonacci = score_ticket_number("0233")
    power_of_two = score_ticket_number("1024")

    assert fibonacci.degree == 4
    assert fibonacci.reasons == ["число Фибоначчи"]
    assert power_of_two.degree == 4
    assert power_of_two.reasons == ["степень двойки"]


def test_ordinary_ticket_is_fifth_class() -> None:
    result = score_ticket_number("0234")

    assert result.degree == 5
    assert result.points == 1
    assert result.label == "обычный билет"
