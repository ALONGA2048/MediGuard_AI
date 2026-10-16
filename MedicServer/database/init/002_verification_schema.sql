CREATE TABLE IF NOT EXISTS public.verification_jobs (
    verification_id uuid PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED')),
    outcome text,
    expected_drug_id bigint REFERENCES public.drug_products(drug_id),
    expected_name text,
    final_prediction text,
    final_confidence double precision,
    decision_source text,
    decision_reason text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.verification_images (
    image_id bigserial PRIMARY KEY,
    verification_id uuid NOT NULL REFERENCES public.verification_jobs(verification_id) ON DELETE CASCADE,
    side text NOT NULL CHECK (side IN ('front', 'back')),
    original_filename text NOT NULL,
    content_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    sha256 char(64) NOT NULL,
    storage_path text NOT NULL,
    UNIQUE (verification_id, side)
);

CREATE TABLE IF NOT EXISTS public.verification_results (
    verification_id uuid PRIMARY KEY REFERENCES public.verification_jobs(verification_id) ON DELETE CASCADE,
    ocr_result jsonb NOT NULL,
    yolo_result jsonb NOT NULL,
    fused_result jsonb NOT NULL,
    result_file text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS verification_jobs_created_at_idx
    ON public.verification_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS verification_jobs_outcome_idx
    ON public.verification_jobs (outcome);

