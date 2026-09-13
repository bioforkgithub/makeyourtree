# SPDX-License-Identifier: MIT
"""Annotation tables: parsing, writing and binding to trees."""
from .loaders import load_annotation, track_from_table, track_from_delimited
from .parser import parse_annotation, write_annotation
from .table import EXTENSION, MAGIC, PROJECT_EXTENSION, AnnotationTable

__all__ = ["AnnotationTable", "MAGIC", "EXTENSION", "PROJECT_EXTENSION",
           "parse_annotation", "write_annotation", "load_annotation",
           "track_from_table", "track_from_delimited"]
