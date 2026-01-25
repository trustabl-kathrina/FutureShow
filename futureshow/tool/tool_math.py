from typing import Any


from fastmcp import FastMCP
import os
from dotenv import load_dotenv
from agents import function_tool
load_dotenv()


@function_tool
def add(a: float, b: float) -> float:
    """Add two numbers (supports int and float)"""
    return float(a) + float(b)

@function_tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers (supports int and float)"""
    return float(a) * float(b)


