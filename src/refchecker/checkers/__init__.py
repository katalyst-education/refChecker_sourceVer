"""
Reference checker implementations for different sources
"""

from .semantic_scholar import NonArxivReferenceChecker
from .local_semantic_scholar import LocalNonArxivReferenceChecker
from .enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from .openalex import OpenAlexReferenceChecker
from .google_books import GoogleBooksReferenceChecker
from .crossref import CrossRefReferenceChecker
from .open_library import OpenLibraryReferenceChecker
from .dnb_sru import DnbSruReferenceChecker, TibSruReferenceChecker, ZdbSruReferenceChecker
from .econbiz import EconBizReferenceChecker
from .arxiv_citation import ArXivCitationChecker
from .acl_anthology import ACLAnthologyReferenceChecker

__all__ = [
    "NonArxivReferenceChecker",
    "LocalNonArxivReferenceChecker",
    "EnhancedHybridReferenceChecker",
    "OpenAlexReferenceChecker",
    "GoogleBooksReferenceChecker",
    "CrossRefReferenceChecker",
    "OpenLibraryReferenceChecker",
    "DnbSruReferenceChecker",
    "EconBizReferenceChecker",
    "TibSruReferenceChecker",
    "ZdbSruReferenceChecker",
    "ArXivCitationChecker",
    "ACLAnthologyReferenceChecker",
]
