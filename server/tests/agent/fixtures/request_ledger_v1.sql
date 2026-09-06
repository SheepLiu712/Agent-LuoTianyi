-- Generated through public handle at e8fac23c (PR115); synthetic request only.
BEGIN TRANSACTION;
CREATE TABLE agent_handle_requests (
	character_id VARCHAR NOT NULL,
	request_id VARCHAR NOT NULL,
	version INTEGER NOT NULL,
	fingerprint VARCHAR NOT NULL,
	report_json TEXT,
	PRIMARY KEY (character_id, request_id)
);
INSERT INTO "agent_handle_requests" VALUES('luotianyi','r',1,'v1:f014208f1be1a662cda9e2ca7df952a134f71ac35f31cf6613e4abbd44c743a7','{"report":{"basis_interaction_revision":3,"considered_pending_stimulus_ids":["m2","m1"],"consumed_pending_stimulus_ids":["m2"],"emitted_plan_ids":["legacy-plan"],"error_code":null,"reconsider_at":null,"request_id":"r","request_status":"completed","retained_pending_stimulus_ids":["m1"],"retryable":false,"trigger_stimulus_id":"m2"},"version":1}');
COMMIT;
