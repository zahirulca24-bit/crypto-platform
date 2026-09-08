from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from schemas import StrategyEvaluateRequest, StrategyDecisionResponse
from services.strategy import evaluate_strategy, get_decisions

router = APIRouter(prefix='/v1/strategies', tags=['Strategies'])

@router.post('/evaluate', response_model=StrategyDecisionResponse)
def evaluate(request: StrategyEvaluateRequest, strategy_name: str, config: dict, db: Session = Depends(get_db)):
    try:
        return evaluate_strategy(request, strategy_name, config, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/decisions', response_model=List[StrategyDecisionResponse])
def fetch_decisions(limit: int = 100, db: Session = Depends(get_db)):
    return get_decisions(db, limit)
