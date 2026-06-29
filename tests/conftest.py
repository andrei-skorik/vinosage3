"""Shared fixtures for VinoSage tests."""
from __future__ import annotations

import pandas as pd
import pytest

_WINES_DATA = [
    {
        "wine_id":         "11111111-0000-0000-0000-000000000001",
        "title":           "Chateau Test Rouge",
        "type":            "Red",
        "grape":           "Cabernet Sauvignon",
        "country":         "France",
        "region":          "Bordeaux",
        "style":           "Rich & Juicy",
        "price_eur_cents": 1500,
        "abv_percent":     13.5,
        "vintage_year":    2020,
        "is_nv":           False,
        "is_active":       True,
        "characteristics": "Bold, tannic, dark fruit",
        "description":     "A classic Bordeaux blend, perfect with a grilled steak or other fish dishes.",
    },
    {
        "wine_id":         "11111111-0000-0000-0000-000000000002",
        "title":           "Weingut Test Riesling",
        "type":            "White",
        "grape":           "Riesling",
        "country":         "Germany",
        "region":          "Mosel",
        "style":           "Crisp & Zesty",
        "price_eur_cents": 1200,
        "abv_percent":     11.5,
        "vintage_year":    2021,
        "is_nv":           False,
        "is_active":       True,
        "characteristics": "Crisp, mineral, citrus",
        "description":     "Light and refreshing, wonderful with grilled salmon or other fish dishes.",
    },
    {
        "wine_id":         "11111111-0000-0000-0000-000000000003",
        "title":           "Bodega Test Malbec",
        "type":            "Red",
        "grape":           "Malbec",
        "country":         "Argentina",
        "region":          "Mendoza",
        "style":           "Rich & Juicy",
        "price_eur_cents": 900,
        "abv_percent":     14.0,
        "vintage_year":    2019,
        "is_nv":           False,
        "is_active":       True,
        "characteristics": "Plum, chocolate, smooth",
        "description":     "Rich Argentine Malbec, ideal for barbecue ribs.",
    },
    {
        "wine_id":         "11111111-0000-0000-0000-000000000004",
        "title":           "Casa Test Rosé",
        "type":            "Rosé",
        "grape":           "Grenache",
        "country":         "Spain",
        "region":          "Rioja",
        "style":           "Light & Fresh",
        "price_eur_cents": 1100,
        "abv_percent":     12.5,
        "vintage_year":    2022,
        "is_nv":           False,
        "is_active":       True,
        "characteristics": "Fresh, strawberry, dry",
        "description":     "Light and refreshing rosé",
    },
    {
        "wine_id":         "11111111-0000-0000-0000-000000000005",
        "title":           "Porto Test Tawny",
        "type":            "Tawny",
        "grape":           "Touriga Nacional",
        "country":         "Portugal",
        "region":          "Douro",
        "style":           "Sweet & Rich",
        "price_eur_cents": 2500,
        "abv_percent":     19.5,
        "vintage_year":    None,
        "is_nv":           True,
        "is_active":       True,
        "characteristics": "Nutty, caramel, dried fruit",
        "description":     "Classic tawny port, lovely with a chocolate dessert.",
    },
    {
        "wine_id":         "11111111-0000-0000-0000-000000000006",
        "title":           "Cantina Test Pinot",
        "type":            "Red",
        "grape":           "Pinot Noir",
        "country":         "Italy",
        "region":          "Alto Adige",
        "style":           "Light & Fruity",
        "price_eur_cents": 1800,
        "abv_percent":     12.5,
        "vintage_year":    2021,
        "is_nv":           False,
        "is_active":       True,
        "characteristics": "Delicate, red fruit, earthy",
        "description":     "Elegant Italian Pinot Noir",
    },
]


@pytest.fixture
def mock_df() -> pd.DataFrame:
    return pd.DataFrame(_WINES_DATA)


@pytest.fixture
def empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=pd.DataFrame(_WINES_DATA).columns)
