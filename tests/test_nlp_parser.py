from __future__ import annotations

from letterboxd_recommender.core.nlp import parse_refinement_prompt


def test_parse_empty_prompt_is_refine_with_no_constraints() -> None:
    result = parse_refinement_prompt(None)
    assert result.intent == "refine"
    assert result.constraints.k is None
    assert result.constraints.include_genres == ()
    assert result.constraints.year_min is None
    assert result.constraints.year_max is None
    assert result.constraints.similar_to_title is None


def test_parse_more_with_genre_and_k() -> None:
    result = parse_refinement_prompt("5 more but from action genre")
    assert result.intent == "more"
    assert result.constraints.k == 5
    assert result.constraints.include_genres == ("action",)


def test_parse_more_like_title() -> None:
    result = parse_refinement_prompt("5 more like Parasite")
    assert result.intent == "more"
    assert result.constraints.k == 5
    assert result.constraints.similar_to_title == "Parasite"


def test_parse_before_year() -> None:
    result = parse_refinement_prompt("More but only from before 1990")
    assert result.intent == "more"
    assert result.constraints.year_min is None
    assert result.constraints.year_max == 1989


def test_parse_between_years() -> None:
    result = parse_refinement_prompt("more between 1990 and 2000")
    assert result.constraints.year_min == 1990
    assert result.constraints.year_max == 2000


def test_parse_country_when_explicit() -> None:
    result = parse_refinement_prompt("5 more from South Korea cinema")
    assert result.constraints.include_countries == ("south korea",)
