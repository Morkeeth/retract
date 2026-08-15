SELECT o.idempotency_key AS original,
       o.status,
       r.idempotency_key AS reversal,
       r.status AS rev_status
FROM effect o JOIN effect r
  ON r.idempotency_key = 'comp:' || o.idempotency_key
 AND r.scope = o.scope
ORDER BY r.created_at DESC LIMIT 1;
