from __future__ import annotations
from typing import Any, Dict, List, Optional


async def get_positions(pool) -> List[Dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.market_id, m.question, m.category, p.side,
                   p.total_shares, p.avg_entry_price, p.current_price,
                   p.unrealized_pnl, p.realized_pnl, p.opened_at, p.updated_at
            FROM positions p
            JOIN markets m ON p.market_id = m.id
            ORDER BY p.opened_at DESC
        """)
    return [dict(r) for r in rows]


async def get_trades(
    pool,
    status: Optional[str] = None,
    side: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    filters = ["1=1"]
    params: List[Any] = []
    i = 1

    if status:
        filters.append(f"t.status = ${i}")
        params.append(status)
        i += 1
    if side:
        filters.append(f"t.side = ${i}")
        params.append(side.upper())
        i += 1

    where = " AND ".join(filters)
    params += [limit, offset]

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT t.id, t.market_id, m.question, m.category, t.side, t.status,
                   t.dollar_size, t.fill_price, t.intended_price, t.slippage_bps,
                   t.filled_shares, t.pnl_realized, t.kelly_fraction,
                   t.placed_at, t.filled_at
            FROM trades t
            JOIN markets m ON t.market_id = m.id
            WHERE {where}
            ORDER BY t.placed_at DESC
            LIMIT ${i} OFFSET ${i+1}
        """, *params)

        total = await conn.fetchval(f"""
            SELECT COUNT(*) FROM trades t WHERE {where}
        """, *params[:-2])

    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


async def get_win_rate_30d(pool) -> Dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE pnl_realized > 0) AS winning,
                COUNT(*) FILTER (WHERE pnl_realized IS NOT NULL) AS total,
                COALESCE(SUM(pnl_realized), 0) AS total_pnl
            FROM trades
            WHERE placed_at > NOW() - INTERVAL '30 days'
              AND status = 'FILLED'
        """)
    total = row["total"] or 0
    winning = row["winning"] or 0
    return {
        "win_rate_30d": winning / total if total > 0 else 0.0,
        "total_trades_30d": total,
        "total_pnl_30d": float(row["total_pnl"] or 0),
    }


async def get_model_performance(pool) -> Dict:
    async with pool.acquire() as conn:
        versions = await conn.fetch("""
            SELECT version, deployed_at, xgb_brier_score, lgbm_brier_score, training_samples
            FROM model_versions ORDER BY deployed_at DESC LIMIT 10
        """)
        calibration = await conn.fetch("""
            SELECT
                ROUND(p.p_yes_ensemble::numeric, 1) AS predicted_bucket,
                AVG(CASE WHEN m.resolution THEN 1.0 ELSE 0.0 END) AS actual_rate,
                COUNT(*) AS count
            FROM predictions p
            JOIN markets m ON p.market_id = m.id
            WHERE m.resolution IS NOT NULL
              AND p.created_at > NOW() - INTERVAL '90 days'
            GROUP BY predicted_bucket
            ORDER BY predicted_bucket
        """)
        accuracy_history = await conn.fetch("""
            SELECT DATE(p.created_at) AS date,
                   AVG(CASE WHEN (p.p_yes_ensemble > 0.5 AND m.resolution = true)
                              OR (p.p_yes_ensemble <= 0.5 AND m.resolution = false)
                            THEN 1.0 ELSE 0.0 END) AS accuracy,
                   COUNT(*) AS predictions
            FROM predictions p
            JOIN markets m ON p.market_id = m.id
            WHERE m.resolution IS NOT NULL
              AND p.created_at > NOW() - INTERVAL '60 days'
            GROUP BY date ORDER BY date
        """)

    return {
        "versions": [dict(r) for r in versions],
        "calibration": [dict(r) for r in calibration],
        "accuracy_history": [dict(r) for r in accuracy_history],
    }


async def get_drawdown_history(pool, days: int = 30) -> List[Dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT date, portfolio_value_eod, total_pnl AS pnl,
                   CASE WHEN MAX(portfolio_value_eod) OVER (ORDER BY date) > 0
                        THEN 1 - portfolio_value_eod / NULLIF(MAX(portfolio_value_eod) OVER (ORDER BY date), 0)
                        ELSE 0 END AS drawdown_pct
            FROM daily_pnl_summary
            WHERE date > CURRENT_DATE - $1
            ORDER BY date
        """, days)
    return [dict(r) for r in rows]


async def get_risk_rejections(pool) -> List[Dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT mistake_category, COUNT(*) as count
            FROM postmortems
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY mistake_category ORDER BY count DESC
        """)
    return [dict(r) for r in rows]
