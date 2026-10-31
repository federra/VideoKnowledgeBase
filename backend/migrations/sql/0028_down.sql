-- Existing foreign keys reject removal if any Qimao source or content exists.
ALTER TABLE platforms DISABLE TRIGGER z_immutable;
DELETE FROM platforms WHERE code='qimao';
ALTER TABLE platforms ENABLE TRIGGER z_immutable;
