-- Owner-only downgrade; FK restrictions still reject referenced platforms.
ALTER TABLE platforms DISABLE TRIGGER z_immutable;
DELETE FROM platforms WHERE code IN ('fanqie','qidian');
ALTER TABLE platforms ENABLE TRIGGER z_immutable;
