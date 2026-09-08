"""
Symbol Selection Router

POST /v1/market-data/symbol-selection  → run a selection scan
GET  /v1/market-data/symbol-selection/{run_id} → retrieve persisted run
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from schemas import SymbolSelectionRequest, SymbolSelectionResponse
from services.symbol_selection import run_symbol_selection, get_run_by_id

router = APIRouter(prefix="/v1/market-data", tags=["Symbol Selection"])


@router.post(
    "/symbol-selection",
    response_model=SymbolSelectionResponse,
    summary="Run a symbol-selection scan",
    description=(
        "Scans the specified exchange, applies filters, scores symbols using "
        "fixed server-controlled weights, and returns a ranked list of the "
        "most suitable trading symbols. Both selected and rejected symbols are "
        "persisted to the database with full metric context for R&D analysis."
    ),
)
def post_symbol_selection(
    request: SymbolSelectionRequest,
    db: Session = Depends(get_db),
) -> SymbolSelectionResponse:
    try:
        return run_symbol_selection(request, db)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.get(
    "/symbol-selection/{run_id}",
    response_model=SymbolSelectionResponse,
    summary="Retrieve a persisted symbol-selection run",
)
def get_symbol_selection(
    run_id: str,
    db: Session = Depends(get_db),
) -> SymbolSelectionResponse:
    try:
        return get_run_by_id(run_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
