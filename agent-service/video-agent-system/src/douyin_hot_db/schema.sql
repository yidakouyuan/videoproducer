PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL,
  message TEXT
);

CREATE TABLE IF NOT EXISTS search_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
  aweme_id TEXT PRIMARY KEY,
  "desc" TEXT,
  create_time INTEGER,
  author_id TEXT,
  author_name TEXT,
  author_sec_uid TEXT,
  author_unique_id TEXT,
  cover_url TEXT,
  video_url TEXT,
  duration INTEGER,
  height INTEGER,
  width INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  keyword TEXT NOT NULL,
  aweme_id TEXT NOT NULL,
  cursor INTEGER,
  rank_in_page INTEGER,
  comment_count INTEGER,
  digg_count INTEGER,
  download_count INTEGER,
  play_count INTEGER,
  share_count INTEGER,
  captured_at TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_run_keyword ON video_snapshots(run_id, keyword);
CREATE INDEX IF NOT EXISTS idx_snapshots_aweme_id ON video_snapshots(aweme_id);

CREATE TABLE IF NOT EXISTS hot_topics (
  topic_id TEXT PRIMARY KEY,
  word TEXT NOT NULL,
  sentence_id TEXT,
  group_id TEXT,
  event_time INTEGER,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hot_topic_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  rank_num INTEGER NOT NULL,
  board TEXT,
  topic_id TEXT NOT NULL,
  word TEXT NOT NULL,
  hot_value INTEGER,
  hot_desc TEXT,
  sentence_tag TEXT,
  url TEXT,
  captured_at TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(topic_id) REFERENCES hot_topics(topic_id)
);

CREATE INDEX IF NOT EXISTS idx_hot_snapshots_run_rank ON hot_topic_snapshots(run_id, rank_num);
CREATE INDEX IF NOT EXISTS idx_hot_snapshots_topic_id ON hot_topic_snapshots(topic_id);

CREATE TABLE IF NOT EXISTS topic_video_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  topic_id TEXT NOT NULL,
  topic_word TEXT NOT NULL,
  topic_rank_num INTEGER,
  sentence_id TEXT,
  group_id TEXT,
  aweme_id TEXT NOT NULL,
  rank_in_topic INTEGER,
  digg_count INTEGER,
  comment_count INTEGER,
  collect_count INTEGER,
  share_count INTEGER,
  play_count INTEGER,
  captured_at TEXT NOT NULL,
  source_url TEXT,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(topic_id) REFERENCES hot_topics(topic_id),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_topic_video_run_topic ON topic_video_snapshots(run_id, topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_video_aweme ON topic_video_snapshots(aweme_id);

CREATE TABLE IF NOT EXISTS video_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  aweme_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  tag_type TEXT,
  captured_at TEXT NOT NULL,
  UNIQUE(aweme_id, tag),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_video_tags_aweme ON video_tags(aweme_id);

CREATE TABLE IF NOT EXISTS video_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  topic_id TEXT,
  aweme_id TEXT,
  comment_id TEXT NOT NULL UNIQUE,
  user_id TEXT,
  user_name TEXT,
  text TEXT,
  digg_count INTEGER,
  reply_total INTEGER,
  create_time INTEGER,
  captured_at TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(topic_id) REFERENCES hot_topics(topic_id),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_video_comments_aweme ON video_comments(aweme_id);

CREATE TABLE IF NOT EXISTS home_feed_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  round_num INTEGER NOT NULL,
  rank_in_round INTEGER NOT NULL,
  aweme_id TEXT NOT NULL,
  source_api_url TEXT,
  page_url TEXT,
  digg_count INTEGER,
  comment_count INTEGER,
  collect_count INTEGER,
  share_count INTEGER,
  play_count INTEGER,
  captured_at TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_home_feed_run_round ON home_feed_snapshots(run_id, round_num);
CREATE INDEX IF NOT EXISTS idx_home_feed_aweme ON home_feed_snapshots(aweme_id);

CREATE TABLE IF NOT EXISTS video_detail_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  aweme_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_api_url TEXT,
  page_url TEXT,
  digg_count INTEGER,
  comment_count INTEGER,
  collect_count INTEGER,
  share_count INTEGER,
  play_count INTEGER,
  captured_at TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(aweme_id) REFERENCES videos(aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_video_detail_run ON video_detail_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_video_detail_aweme ON video_detail_snapshots(aweme_id);
