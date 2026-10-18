-- Project Atlas schema. Runs once on first MySQL start (docker-entrypoint-initdb.d).
CREATE DATABASE IF NOT EXISTS atlas CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE atlas;

-- Report catalogue. Existence/metadata of every report is public; figures are not.
CREATE TABLE reports (
  id          VARCHAR(10)  NOT NULL PRIMARY KEY,
  title       VARCHAR(255) NOT NULL,
  publisher   VARCHAR(120) NOT NULL,
  published   DATE         NOT NULL,
  sector      VARCHAR(80)  NOT NULL,
  market      VARCHAR(120) NOT NULL,
  region      VARCHAR(40)  NOT NULL,
  access      ENUM('paid','public excerpt') NOT NULL,
  keywords    VARCHAR(255) NOT NULL COMMENT 'comma separated, used for market detection',
  summary     VARCHAR(500) NOT NULL COMMENT 'scope description, must not contain figures'
) ENGINE=InnoDB;

-- Structured figures extracted from the reports (entitlement-filtered in code).
CREATE TABLE market_metrics (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  report_id    VARCHAR(10)  NOT NULL,
  market       VARCHAR(120) NOT NULL,
  metric       ENUM('market_size','cagr','regional_share') NOT NULL,
  region       VARCHAR(40)  NOT NULL,
  period_start SMALLINT     NOT NULL,
  period_end   SMALLINT     NOT NULL,
  value        DECIMAL(12,4) NOT NULL,
  unit         ENUM('USD_B','PCT') NOT NULL,
  scope_note   VARCHAR(255) NOT NULL,
  page         SMALLINT     NOT NULL,
  CONSTRAINT fk_metric_report FOREIGN KEY (report_id) REFERENCES reports(id),
  INDEX idx_metric_report (report_id),
  INDEX idx_metric_market (market)
) ENGINE=InnoDB;

CREATE TABLE clients (
  id            VARCHAR(10)  NOT NULL PRIMARY KEY,
  company       VARCHAR(160) NOT NULL,
  contact_email VARCHAR(160) NOT NULL COMMENT 'CONFIDENTIAL - no service user can read this column'
) ENGINE=InnoDB;

-- Normalised form of the appendix "purchased_reports" column.
CREATE TABLE client_purchases (
  client_id    VARCHAR(10) NOT NULL,
  report_id    VARCHAR(10) NOT NULL,
  purchased_at DATE        NOT NULL,
  PRIMARY KEY (client_id, report_id),
  CONSTRAINT fk_purchase_client FOREIGN KEY (client_id) REFERENCES clients(id),
  CONSTRAINT fk_purchase_report FOREIGN KEY (report_id) REFERENCES reports(id)
) ENGINE=InnoDB;

CREATE TABLE escalations (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  request_id   CHAR(36)      NULL,
  client_id    VARCHAR(10)   NOT NULL,
  question     TEXT          NOT NULL,
  reason       VARCHAR(500)  NOT NULL,
  confidence   DECIMAL(4,3)  NULL,
  draft_answer TEXT          NULL COMMENT 'internal only, for the analyst',
  source       ENUM('copilot','portal_fallback') NOT NULL DEFAULT 'copilot',
  status       ENUM('open','in_progress','closed') NOT NULL DEFAULT 'open',
  created_at   TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_esc_status (status, created_at)
) ENGINE=InnoDB;

CREATE TABLE request_log (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  request_id        CHAR(36)     NOT NULL,
  client_id         VARCHAR(10)  NOT NULL,
  question          TEXT         NOT NULL,
  route             VARCHAR(40)  NOT NULL,
  confidence        DECIMAL(4,3) NULL,
  escalated         TINYINT(1)   NOT NULL DEFAULT 0,
  cached            TINYINT(1)   NOT NULL DEFAULT 0,
  latency_ms        INT          NOT NULL,
  prompt_tokens     INT          NOT NULL DEFAULT 0,
  completion_tokens INT          NOT NULL DEFAULT 0,
  cost_usd          DECIMAL(10,6) NOT NULL DEFAULT 0,
  trace_json        JSON         NULL,
  created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_req_client (client_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE security_events (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  request_id  CHAR(36)     NULL,
  client_id   VARCHAR(10)  NULL,
  event_type  VARCHAR(40)  NOT NULL,
  source      VARCHAR(120) NOT NULL,
  detail      VARCHAR(1000) NOT NULL,
  created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_sec_type (event_type, created_at)
) ENGINE=InnoDB;

-- CodeIgniter portal tables
CREATE TABLE conversations (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  client_id     VARCHAR(10)  NOT NULL,
  chat_session  CHAR(32)     NOT NULL,
  question      TEXT         NOT NULL,
  answer        MEDIUMTEXT   NOT NULL,
  response_json MEDIUMTEXT   NULL,
  confidence    DECIMAL(4,3) NULL,
  escalated     TINYINT(1)   NOT NULL DEFAULT 0,
  status        ENUM('ok','fallback') NOT NULL DEFAULT 'ok',
  request_id    CHAR(36)     NULL,
  created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_conv_session (client_id, chat_session, created_at)
) ENGINE=InnoDB;

CREATE TABLE feedback (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  conversation_id INT        NOT NULL,
  rating          TINYINT    NOT NULL COMMENT '1 = thumbs up, -1 = thumbs down',
  created_at      TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_feedback_conv (conversation_id),
  CONSTRAINT fk_feedback_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id)
) ENGINE=InnoDB;
