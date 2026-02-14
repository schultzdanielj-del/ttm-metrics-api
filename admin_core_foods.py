@app.post("/api/admin/bulk-core-foods", tags=["Admin"])
def admin_bulk_core_foods(body: dict, db: Session = Depends(get_db)):
    """
    Bulk insert core foods checkins. Bypasses date validation.
    Body: {"key": "ADMIN_KEY", "records": [{"user_id", "date", "message_id", "timestamp", "xp_awarded"}, ...]}
    """
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")
    if body.get("key") != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    records = body.get("records", [])
    if not records:
        raise HTTPException(status_code=400, detail="No records provided")
    inserted = 0
    skipped = 0
    for r in records:
        user_id = r.get("user_id", "")
        date = r.get("date", "")
        if not user_id or not date:
            skipped += 1
            continue
        existing = db.query(CoreFoodsCheckin).filter(
            and_(CoreFoodsCheckin.user_id == user_id, CoreFoodsCheckin.date == date)
        ).first()
        if existing:
            skipped += 1
            continue
        ts_str = r.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str) if ts_str else datetime.utcnow()
        except:
            ts = datetime.utcnow()
        db.add(CoreFoodsCheckin(
            user_id=user_id, date=date,
            message_id=r.get("message_id", f"migration-{date}"),
            timestamp=ts, xp_awarded=r.get("xp_awarded", 0)
        ))
        inserted += 1
    db.commit()
    from sqlalchemy import func
    total = db.query(func.count(CoreFoodsCheckin.id)).scalar()
    return {"inserted": inserted, "skipped": skipped, "total_in_table": total}
