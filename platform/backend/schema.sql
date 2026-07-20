CREATE TABLE IF NOT EXISTS users (
  id CHAR(36) PRIMARY KEY,
  email VARCHAR(190) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(120) NOT NULL,
  company VARCHAR(190) NOT NULL,
  account_status ENUM('active','disabled') NOT NULL DEFAULT 'active',
  plan ENUM('free','pro') NOT NULL DEFAULT 'free',
  pro_expires_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_users_plan (plan, pro_expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS sessions (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  revoked_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_sessions_user (user_id),
  INDEX idx_sessions_expiry (expires_at, revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS buyer_compliance_profiles (
  user_id CHAR(36) PRIMARY KEY,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  organization_legal_name VARCHAR(190) NOT NULL,
  security_contact_email VARCHAR(190) NOT NULL,
  deployment_boundary ENUM('qtail_cloud','customer_vpc','on_prem') NOT NULL,
  data_residency VARCHAR(190) NOT NULL,
  retention_days SMALLINT UNSIGNED NOT NULL,
  deletion_sla_days SMALLINT UNSIGNED NOT NULL,
  source_rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  derivative_rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  restricted_data_excluded BOOLEAN NOT NULL DEFAULT FALSE,
  subprocessor_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
  profile_sha256 CHAR(64) NOT NULL,
  status ENUM('received','approved','rejected') NOT NULL DEFAULT 'received',
  review_note TEXT NULL,
  submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_compliance_profile_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_compliance_profile_status (status, submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS legal_acceptances (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  document_code ENUM('terms','privacy','dpa') NOT NULL,
  document_version VARCHAR(40) NOT NULL,
  acceptance_sha256 CHAR(64) NOT NULL,
  context_json JSON NOT NULL,
  accepted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_at DATETIME NULL,
  CONSTRAINT fk_legal_acceptance_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_legal_acceptance_version (user_id, document_code, document_version),
  INDEX idx_legal_acceptance_user (user_id, accepted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_access_applications (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  role VARCHAR(120) NOT NULL,
  use_case VARCHAR(300) NOT NULL,
  data_format VARCHAR(160) NOT NULL,
  monthly_volume VARCHAR(160) NOT NULL,
  pilot_goal TEXT NOT NULL,
  status ENUM('received','approved','rejected') NOT NULL DEFAULT 'received',
  review_note TEXT NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_api_application_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_api_application_user (user_id, created_at),
  INDEX idx_api_application_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_keys (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  label VARCHAR(120) NOT NULL,
  key_prefix VARCHAR(32) NOT NULL,
  key_hash CHAR(64) NOT NULL UNIQUE,
  scopes JSON NOT NULL,
  status ENUM('active','revoked') NOT NULL DEFAULT 'active',
  last_used_at DATETIME NULL,
  expires_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_api_keys_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_api_keys_user (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS payment_orders (
  id CHAR(36) PRIMARY KEY,
  merchant_order_no VARCHAR(32) NOT NULL,
  user_id CHAR(36) NOT NULL,
  plan_code VARCHAR(40) NOT NULL,
  channel ENUM('wechat','alipay') NOT NULL,
  payment_mode ENUM('manual_qr_verification','official_merchant') NOT NULL DEFAULT 'manual_qr_verification',
  amount_cents INT UNSIGNED NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'CNY',
  status ENUM('pending','under_review','paid','rejected','expired','refunded') NOT NULL DEFAULT 'pending',
  payment_reference VARCHAR(255) NULL,
  provider_transaction_id VARCHAR(128) NULL,
  provider_event_id VARCHAR(190) NULL,
  provider_payload_sha256 CHAR(64) NULL,
  provider_verified_at DATETIME NULL,
  checkout_url TEXT NULL,
  review_note TEXT NULL,
  submitted_at DATETIME NULL,
  paid_at DATETIME NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_payment_order_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_payment_merchant_order (merchant_order_no),
  INDEX idx_payment_order_user (user_id, created_at),
  INDEX idx_payment_order_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS invoice_requests (
  id CHAR(36) PRIMARY KEY,
  order_id CHAR(36) NOT NULL,
  user_id CHAR(36) NOT NULL,
  invoice_title VARCHAR(190) NOT NULL,
  taxpayer_id VARCHAR(32) NOT NULL,
  invoice_email VARCHAR(190) NOT NULL,
  status ENUM('requested','issued','rejected','cancelled') NOT NULL DEFAULT 'requested',
  invoice_number VARCHAR(120) NULL,
  invoice_document_url TEXT NULL,
  cancellation_reference VARCHAR(255) NULL,
  review_note TEXT NULL,
  requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME NULL,
  issued_at DATETIME NULL,
  cancelled_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_invoice_order FOREIGN KEY (order_id) REFERENCES payment_orders(id) ON DELETE RESTRICT,
  CONSTRAINT fk_invoice_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_invoice_user (user_id, requested_at),
  INDEX idx_invoice_status (status, requested_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS refund_requests (
  id CHAR(36) PRIMARY KEY,
  merchant_refund_no VARCHAR(64) NOT NULL,
  order_id CHAR(36) NOT NULL UNIQUE,
  user_id CHAR(36) NOT NULL,
  amount_cents INT UNSIGNED NOT NULL,
  reason TEXT NOT NULL,
  status ENUM('requested','approved','processing','rejected','failed','completed') NOT NULL DEFAULT 'requested',
  refund_reference VARCHAR(255) NULL,
  provider_refund_id VARCHAR(128) NULL,
  provider_event_id VARCHAR(190) NULL,
  provider_payload_sha256 CHAR(64) NULL,
  provider_verified_at DATETIME NULL,
  review_note TEXT NULL,
  requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME NULL,
  completed_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_refund_order FOREIGN KEY (order_id) REFERENCES payment_orders(id) ON DELETE RESTRICT,
  CONSTRAINT fk_refund_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_refund_merchant_order (merchant_refund_no),
  INDEX idx_refund_user (user_id, requested_at),
  INDEX idx_refund_status (status, requested_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS payment_provider_events (
  id CHAR(36) PRIMARY KEY,
  channel ENUM('wechat','alipay') NOT NULL,
  event_id VARCHAR(190) NOT NULL,
  event_type ENUM('payment','refund') NOT NULL,
  order_id CHAR(36) NULL,
  refund_id CHAR(36) NULL,
  provider_transaction_id VARCHAR(128) NULL,
  payload_sha256 CHAR(64) NOT NULL,
  signature_serial VARCHAR(128) NULL,
  status ENUM('accepted','rejected') NOT NULL,
  failure_code VARCHAR(120) NULL,
  received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at DATETIME NULL,
  CONSTRAINT fk_provider_event_order FOREIGN KEY (order_id) REFERENCES payment_orders(id) ON DELETE RESTRICT,
  CONSTRAINT fk_provider_event_refund FOREIGN KEY (refund_id) REFERENCES refund_requests(id) ON DELETE RESTRICT,
  UNIQUE KEY uq_provider_event (channel, event_id),
  INDEX idx_provider_event_order (order_id, received_at),
  INDEX idx_provider_event_refund (refund_id, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS generation_jobs (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  api_key_id CHAR(36) NULL,
  filename VARCHAR(255) NOT NULL,
  robot_model VARCHAR(160) NOT NULL,
  control_frequency_hz DECIMAL(8,2) NOT NULL,
  sensors VARCHAR(255) NOT NULL,
  training_format VARCHAR(120) NOT NULL,
  production_backend VARCHAR(160) NOT NULL,
  synthetic_budget BIGINT UNSIGNED NOT NULL,
  delivery_product VARCHAR(64) NOT NULL DEFAULT 'allocation_plan',
  trajectory_count SMALLINT UNSIGNED NULL,
  status ENUM('queued','running','completed','failed') NOT NULL DEFAULT 'queued',
  gate_evaluation JSON NOT NULL,
  input_sha256 CHAR(64) NOT NULL,
  input_path TEXT NULL,
  output_json JSON NULL,
  output_path TEXT NULL,
  error_message TEXT NULL,
  attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
  max_attempts TINYINT UNSIGNED NOT NULL DEFAULT 3,
  next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  worker_id VARCHAR(190) NULL,
  lease_expires_at DATETIME NULL,
  heartbeat_at DATETIME NULL,
  last_error_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  CONSTRAINT fk_generation_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_generation_api_key FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE SET NULL,
  INDEX idx_generation_user (user_id, created_at),
  INDEX idx_generation_status (status, created_at),
  INDEX idx_generation_queue (status, next_attempt_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS generation_data_rights (
  generation_job_id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  source_type ENUM('customer_owned','licensed','public_open','synthetic') NOT NULL,
  license_basis VARCHAR(500) NOT NULL,
  contains_personal_data BOOLEAN NOT NULL DEFAULT FALSE,
  retention_days SMALLINT UNSIGNED NOT NULL,
  source_rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  derivative_rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  restricted_data_excluded BOOLEAN NOT NULL DEFAULT FALSE,
  attestation_version VARCHAR(40) NOT NULL,
  attestation_sha256 CHAR(64) NOT NULL,
  accepted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_generation_rights_job FOREIGN KEY (generation_job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_generation_rights_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_generation_rights_user (user_id, accepted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS data_deletion_requests (
  id CHAR(36) PRIMARY KEY,
  generation_job_id CHAR(36) NOT NULL,
  user_id CHAR(36) NOT NULL,
  request_source ENUM('buyer','retention','account_closure') NOT NULL DEFAULT 'buyer',
  reason TEXT NOT NULL,
  status ENUM('requested','processing','rejected','completed') NOT NULL DEFAULT 'requested',
  due_at DATETIME NOT NULL,
  deletion_manifest JSON NULL,
  deletion_sha256 CHAR(64) NULL,
  files_deleted INT UNSIGNED NOT NULL DEFAULT 0,
  bytes_deleted BIGINT UNSIGNED NOT NULL DEFAULT 0,
  review_note TEXT NULL,
  requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME NULL,
  completed_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_deletion_job FOREIGN KEY (generation_job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_deletion_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_deletion_job (generation_job_id),
  INDEX idx_deletion_user (user_id, requested_at),
  INDEX idx_deletion_status_due (status, due_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS system_settings (
  setting_key VARCHAR(120) PRIMARY KEY,
  setting_value VARCHAR(255) NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_usage_daily (
  user_id CHAR(36) NOT NULL,
  usage_date DATE NOT NULL,
  generation_count INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, usage_date),
  CONSTRAINT fk_api_usage_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS procurement_cases (
  id CHAR(36) PRIMARY KEY,
  user_id CHAR(36) NOT NULL,
  generation_job_id CHAR(36) NOT NULL,
  title VARCHAR(190) NOT NULL,
  buyer_owner VARCHAR(190) NOT NULL,
  pilot_scope TEXT NOT NULL,
  status ENUM('active','contract_ready','contracted','closed') NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_procurement_case_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_procurement_case_job FOREIGN KEY (generation_job_id) REFERENCES generation_jobs(id) ON DELETE RESTRICT,
  UNIQUE KEY uq_procurement_case_job (generation_job_id),
  INDEX idx_procurement_case_user (user_id, created_at),
  INDEX idx_procurement_case_status (status, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS procurement_gate_evidence (
  id CHAR(36) PRIMARY KEY,
  case_id CHAR(36) NOT NULL,
  user_id CHAR(36) NOT NULL,
  gate_number TINYINT UNSIGNED NOT NULL,
  evidence_json JSON NOT NULL,
  evidence_sha256 CHAR(64) NOT NULL,
  evidence_scope ENUM('simulation','buyer_external') NOT NULL DEFAULT 'simulation',
  contract_eligible BOOLEAN NOT NULL DEFAULT FALSE,
  automated_status ENUM('passed','failed') NOT NULL,
  automated_findings JSON NOT NULL,
  status ENUM('received','approved','rejected') NOT NULL DEFAULT 'received',
  review_note TEXT NULL,
  verification_reference VARCHAR(255) NULL,
  reviewer_name VARCHAR(190) NULL,
  review_attestation_sha256 CHAR(64) NULL,
  reviewed_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_gate_evidence_case FOREIGN KEY (case_id) REFERENCES procurement_cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_gate_evidence_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT chk_gate_evidence_number CHECK (gate_number BETWEEN 1 AND 3),
  INDEX idx_gate_evidence_case (case_id, gate_number, created_at),
  INDEX idx_gate_evidence_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS procurement_contracts (
  id CHAR(36) PRIMARY KEY,
  case_id CHAR(36) NOT NULL,
  user_id CHAR(36) NOT NULL,
  version INT UNSIGNED NOT NULL DEFAULT 1,
  status ENUM('ready','signed','void') NOT NULL DEFAULT 'ready',
  acceptance_snapshot JSON NOT NULL,
  contract_reference VARCHAR(255) NULL,
  executed_document_sha256 CHAR(64) NULL,
  provider_signatory VARCHAR(190) NULL,
  provider_signature_sha256 CHAR(64) NULL,
  buyer_signatory VARCHAR(190) NULL,
  buyer_signature_sha256 CHAR(64) NULL,
  effective_date DATE NULL,
  execution_attestation_sha256 CHAR(64) NULL,
  issued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  signed_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_procurement_contract_case FOREIGN KEY (case_id) REFERENCES procurement_cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_procurement_contract_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_procurement_contract_case_version (case_id, version),
  INDEX idx_procurement_contract_status (status, issued_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  actor_user_id CHAR(36) NULL,
  event_type VARCHAR(120) NOT NULL,
  object_type VARCHAR(80) NOT NULL,
  object_id VARCHAR(80) NOT NULL,
  event_json JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_audit_actor FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_audit_object (object_type, object_id, created_at),
  INDEX idx_audit_actor (actor_user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
