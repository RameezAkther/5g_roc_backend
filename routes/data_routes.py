from fastapi import APIRouter
import os
import pandas as pd

# from dependencies import get_current_user   ✅ enable later to protect routes

router = APIRouter(tags=["5G Data"])

BASE_DATA_DIR = "./data"


@router.get("/cities")
def get_cities():
    return os.listdir(BASE_DATA_DIR)


@router.get("/nodes/{city}")
def get_nodes(city: str):
    return os.listdir(os.path.join(BASE_DATA_DIR, city))


@router.get("/node-data/{city}/{node}")
def get_node_data(city: str, node: str):
    filepath = os.path.join(BASE_DATA_DIR, city, node)
    df = pd.read_csv(filepath)
    return df.tail(200).to_dict(orient="records")
