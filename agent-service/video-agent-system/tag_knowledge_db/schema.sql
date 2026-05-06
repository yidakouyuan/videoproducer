PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL,
  input_dir TEXT NOT NULL,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_processed INTEGER NOT NULL DEFAULT 0,
  records_seen INTEGER NOT NULL DEFAULT 0,
  records_ingested INTEGER NOT NULL DEFAULT 0,
  message TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
  source_file TEXT PRIMARY KEY,
  file_mtime REAL NOT NULL,
  file_size INTEGER NOT NULL,
  file_sha1 TEXT NOT NULL,
  first_processed_at TEXT NOT NULL,
  last_processed_at TEXT NOT NULL,
  input_record_count INTEGER NOT NULL DEFAULT 0,
  output_record_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS videos (
  aweme_id TEXT PRIMARY KEY,
  title TEXT,
  author_id TEXT,
  author_name TEXT,
  page_url TEXT,
  source_kind TEXT,
  source_api_url TEXT,
  create_time INTEGER,
  captured_at TEXT,
  digg_count INTEGER,
  comment_count INTEGER,
  collect_count INTEGER,
  share_count INTEGER,
  play_count INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_create_time ON videos(create_time);
CREATE INDEX IF NOT EXISTS idx_videos_last_seen_at ON videos(last_seen_at);

CREATE TABLE IF NOT EXISTS raw_tags (
  raw_tag_norm TEXT PRIMARY KEY,
  raw_tag_display TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  video_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS video_raw_tags (
  aweme_id TEXT NOT NULL,
  raw_tag_norm TEXT NOT NULL,
  source TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (aweme_id, raw_tag_norm),
  FOREIGN KEY (aweme_id) REFERENCES videos(aweme_id) ON DELETE CASCADE,
  FOREIGN KEY (raw_tag_norm) REFERENCES raw_tags(raw_tag_norm) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_video_raw_tags_tag ON video_raw_tags(raw_tag_norm);

CREATE TABLE IF NOT EXISTS canonical_tags (
  canonical_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT NOT NULL UNIQUE,
  tag_kind TEXT NOT NULL DEFAULT 'unknown',
  kind_source TEXT NOT NULL DEFAULT 'pending',
  kind_confidence REAL,
  merged_into INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (tag_kind IN ('unknown', 'topic', 'campaign')),
  FOREIGN KEY (merged_into) REFERENCES canonical_tags(canonical_tag_id)
);

CREATE INDEX IF NOT EXISTS idx_canonical_tags_kind ON canonical_tags(tag_kind);

CREATE TABLE IF NOT EXISTS tag_aliases (
  raw_tag_norm TEXT PRIMARY KEY,
  canonical_tag_id INTEGER NOT NULL,
  alias_source TEXT NOT NULL,
  confidence REAL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (raw_tag_norm) REFERENCES raw_tags(raw_tag_norm) ON DELETE CASCADE,
  FOREIGN KEY (canonical_tag_id) REFERENCES canonical_tags(canonical_tag_id)
);

CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical ON tag_aliases(canonical_tag_id);

CREATE TABLE IF NOT EXISTS canonical_tag_stats (
  canonical_tag_id INTEGER PRIMARY KEY,
  video_count INTEGER NOT NULL,
  digg_sum INTEGER NOT NULL,
  collect_sum INTEGER NOT NULL,
  comment_sum INTEGER NOT NULL,
  share_sum INTEGER NOT NULL,
  score REAL NOT NULL,
  title_samples_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (canonical_tag_id) REFERENCES canonical_tags(canonical_tag_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tag_cooccurrence (
  src_tag_id INTEGER NOT NULL,
  dst_tag_id INTEGER NOT NULL,
  co_cnt_total INTEGER NOT NULL,
  co_cnt_7d INTEGER NOT NULL,
  co_cnt_30d INTEGER NOT NULL,
  decayed_weight REAL NOT NULL,
  last_event_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (src_tag_id, dst_tag_id),
  CHECK (src_tag_id < dst_tag_id),
  FOREIGN KEY (src_tag_id) REFERENCES canonical_tags(canonical_tag_id) ON DELETE CASCADE,
  FOREIGN KEY (dst_tag_id) REFERENCES canonical_tags(canonical_tag_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tag_cooccurrence_src ON tag_cooccurrence(src_tag_id);
CREATE INDEX IF NOT EXISTS idx_tag_cooccurrence_dst ON tag_cooccurrence(dst_tag_id);

CREATE TABLE IF NOT EXISTS communities (
  community_id INTEGER PRIMARY KEY AUTOINCREMENT,
  algo TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  generated_at TEXT NOT NULL,
  topic_count INTEGER NOT NULL,
  report_text TEXT,
  report_source TEXT NOT NULL DEFAULT 'template',
  report_title TEXT,
  report_summary TEXT,
  report_rating REAL,
  report_findings_json TEXT
);

CREATE TABLE IF NOT EXISTS community_members (
  community_id INTEGER NOT NULL,
  canonical_tag_id INTEGER NOT NULL,
  member_rank INTEGER NOT NULL,
  score REAL NOT NULL,
  PRIMARY KEY (community_id, canonical_tag_id),
  FOREIGN KEY (community_id) REFERENCES communities(community_id) ON DELETE CASCADE,
  FOREIGN KEY (canonical_tag_id) REFERENCES canonical_tags(canonical_tag_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_community_members_tag ON community_members(canonical_tag_id);

CREATE TABLE IF NOT EXISTS tag_cards (
  canonical_tag_id INTEGER PRIMARY KEY,
  card_text TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'template',
  FOREIGN KEY (canonical_tag_id) REFERENCES canonical_tags(canonical_tag_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS llm_tasks (
  task_id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_type TEXT NOT NULL,
  task_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending',
  priority INTEGER NOT NULL DEFAULT 100,
  payload_json TEXT NOT NULL,
  result_json TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_tasks_status_priority ON llm_tasks(status, priority, task_id);

CREATE VIEW IF NOT EXISTS active_canonical_tags AS
SELECT *
FROM canonical_tags
WHERE merged_into IS NULL;

CREATE VIEW IF NOT EXISTS topic_topic_edges AS
SELECT
  e.src_tag_id,
  e.dst_tag_id,
  e.co_cnt_total,
  e.co_cnt_7d,
  e.co_cnt_30d,
  e.decayed_weight,
  e.last_event_at
FROM tag_cooccurrence e
JOIN canonical_tags s ON s.canonical_tag_id = e.src_tag_id
JOIN canonical_tags d ON d.canonical_tag_id = e.dst_tag_id
WHERE s.tag_kind = 'topic'
  AND d.tag_kind = 'topic'
  AND s.merged_into IS NULL
  AND d.merged_into IS NULL;

CREATE VIEW IF NOT EXISTS campaign_topic_edges AS
SELECT
  CASE WHEN s.tag_kind = 'campaign' THEN e.src_tag_id ELSE e.dst_tag_id END AS campaign_tag_id,
  CASE WHEN s.tag_kind = 'topic' THEN e.src_tag_id ELSE e.dst_tag_id END AS topic_tag_id,
  e.co_cnt_total,
  e.co_cnt_7d,
  e.co_cnt_30d,
  e.decayed_weight,
  e.last_event_at
FROM tag_cooccurrence e
JOIN canonical_tags s ON s.canonical_tag_id = e.src_tag_id
JOIN canonical_tags d ON d.canonical_tag_id = e.dst_tag_id
WHERE (
    (s.tag_kind = 'campaign' AND d.tag_kind = 'topic')
    OR (s.tag_kind = 'topic' AND d.tag_kind = 'campaign')
  )
  AND s.merged_into IS NULL
  AND d.merged_into IS NULL;
