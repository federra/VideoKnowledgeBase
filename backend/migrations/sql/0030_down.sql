-- Drop dependent pointers first; no CASCADE and no historical tables are touched.
ALTER TABLE topic_cards DROP CONSTRAINT fk_topic_cards_id_current_revision_id;
ALTER TABLE topic_cards DROP CONSTRAINT fk_topic_cards_id_selected_revision_id;
ALTER TABLE topic_sparks DROP CONSTRAINT fk_topic_sparks_id_current_revision_id;
DROP TABLE topic_handoffs;
DROP TABLE topic_saved_generations;
DROP TABLE topic_spark_revisions;
DROP TABLE topic_sparks;
DROP TABLE topic_revisions;
DROP TABLE topic_cards;
DROP FUNCTION cip_topic_revision_guard();
