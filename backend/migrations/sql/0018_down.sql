-- Existing Hongguo references reject downgrade through foreign keys.
ALTER TABLE platforms DISABLE TRIGGER z_immutable;
DELETE FROM platforms WHERE code='hongguo';
ALTER TABLE platforms ENABLE TRIGGER z_immutable;
