--
-- PostgreSQL database dump
--

\restrict FJP8xdyne2LtFqsUub3mBACBuxbUmvfq97pNSexP1QOqr19mAcpsBMpnBhNoMqU

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: dosage_form_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dosage_form_aliases (
    alias_id bigint NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    dosage_form_code text NOT NULL,
    canonical_en text NOT NULL,
    canonical_zh text,
    release_type text,
    source text DEFAULT 'manual'::text NOT NULL
);


--
-- Name: dosage_form_aliases_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dosage_form_aliases_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dosage_form_aliases_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dosage_form_aliases_alias_id_seq OWNED BY public.dosage_form_aliases.alias_id;


--
-- Name: drug_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.drug_aliases (
    alias_id bigint NOT NULL,
    drug_id bigint NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    language_code text NOT NULL,
    alias_type text DEFAULT 'manual'::text NOT NULL,
    CONSTRAINT drug_aliases_language_code_check CHECK ((language_code = ANY (ARRAY['en'::text, 'zh'::text])))
);


--
-- Name: drug_aliases_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.drug_aliases_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drug_aliases_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.drug_aliases_alias_id_seq OWNED BY public.drug_aliases.alias_id;


--
-- Name: drug_barcodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.drug_barcodes (
    barcode_id bigint NOT NULL,
    drug_id bigint NOT NULL,
    barcode text NOT NULL,
    barcode_type text DEFAULT 'EAN-13'::text NOT NULL
);


--
-- Name: drug_barcodes_barcode_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.drug_barcodes_barcode_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drug_barcodes_barcode_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.drug_barcodes_barcode_id_seq OWNED BY public.drug_barcodes.barcode_id;


--
-- Name: drug_ingredients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.drug_ingredients (
    drug_ingredient_id bigint NOT NULL,
    drug_id bigint NOT NULL,
    ingredient_order integer NOT NULL,
    ingredient_raw text,
    ingredient_normalized text NOT NULL,
    language_code text
);


--
-- Name: drug_ingredients_drug_ingredient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.drug_ingredients_drug_ingredient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drug_ingredients_drug_ingredient_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.drug_ingredients_drug_ingredient_id_seq OWNED BY public.drug_ingredients.drug_ingredient_id;


--
-- Name: drug_products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.drug_products (
    drug_id bigint NOT NULL,
    source_record_key text NOT NULL,
    identity_key_type text NOT NULL,
    folder_name text,
    drug_name_en text,
    drug_name_zh text,
    normalized_name_en text,
    normalized_name_zh text,
    product_family_key text,
    strength_raw text,
    strength_normalized text,
    dosage_form_en text,
    dosage_form_zh text,
    dosage_form_code text,
    release_type text,
    license_kind text,
    license_number text,
    manufacturer_en text,
    manufacturer_zh text,
    source_row_number integer,
    import_run_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT drug_products_check CHECK ((((license_kind IS NULL) AND (license_number IS NULL)) OR ((license_kind IS NOT NULL) AND (license_number IS NOT NULL)))),
    CONSTRAINT drug_products_identity_key_type_check CHECK ((identity_key_type = ANY (ARRAY['LICENSE'::text, 'BARCODE'::text, 'COMPOSITE_EN'::text, 'COMPOSITE_ZH'::text]))),
    CONSTRAINT drug_products_license_kind_check CHECK (((license_kind = ANY (ARRAY['製'::text, '輸'::text])) OR (license_kind IS NULL)))
);


--
-- Name: drug_products_drug_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.drug_products_drug_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drug_products_drug_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.drug_products_drug_id_seq OWNED BY public.drug_products.drug_id;


--
-- Name: import_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_issues (
    issue_id bigint NOT NULL,
    import_run_id bigint NOT NULL,
    source_row_number integer NOT NULL,
    folder_name text,
    issue_code text NOT NULL,
    issue_message text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: import_issues_issue_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.import_issues_issue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_issues_issue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.import_issues_issue_id_seq OWNED BY public.import_issues.issue_id;


--
-- Name: import_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_runs (
    import_run_id bigint NOT NULL,
    source_file_name text NOT NULL,
    source_file_sha256 text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text NOT NULL,
    rows_read integer DEFAULT 0 NOT NULL,
    rows_inserted integer DEFAULT 0 NOT NULL,
    rows_updated integer DEFAULT 0 NOT NULL,
    rows_skipped integer DEFAULT 0 NOT NULL,
    rows_with_issues integer DEFAULT 0 NOT NULL,
    CONSTRAINT import_runs_status_check CHECK ((status = ANY (ARRAY['RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text, 'DRY_RUN'::text])))
);


--
-- Name: import_runs_import_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.import_runs_import_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_runs_import_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.import_runs_import_run_id_seq OWNED BY public.import_runs.import_run_id;


--
-- Name: ingredient_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ingredient_aliases (
    alias_id bigint NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    canonical text NOT NULL,
    language_code text,
    source text DEFAULT 'manual'::text NOT NULL
);


--
-- Name: ingredient_aliases_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ingredient_aliases_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingredient_aliases_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ingredient_aliases_alias_id_seq OWNED BY public.ingredient_aliases.alias_id;


--
-- Name: manufacturer_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.manufacturer_aliases (
    alias_id bigint NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    canonical text NOT NULL,
    alias_type text DEFAULT 'manufacturer'::text NOT NULL,
    source text DEFAULT 'manual'::text NOT NULL
);


--
-- Name: manufacturer_aliases_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.manufacturer_aliases_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: manufacturer_aliases_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.manufacturer_aliases_alias_id_seq OWNED BY public.manufacturer_aliases.alias_id;


--
-- Name: matching_weights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.matching_weights (
    field_name text NOT NULL,
    weight numeric(6,2) NOT NULL,
    CONSTRAINT matching_weights_field_name_check CHECK ((field_name = ANY (ARRAY['drug_name'::text, 'ingredient'::text, 'strength'::text, 'manufacturer'::text, 'dosage_form'::text]))),
    CONSTRAINT matching_weights_weight_check CHECK ((weight >= (0)::numeric))
);


--
-- Name: normalization_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.normalization_aliases (
    alias_id bigint NOT NULL,
    field_name text NOT NULL,
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    canonical text NOT NULL
);


--
-- Name: normalization_aliases_alias_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.normalization_aliases_alias_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: normalization_aliases_alias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.normalization_aliases_alias_id_seq OWNED BY public.normalization_aliases.alias_id;


--
-- Name: v_drug_family; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_drug_family AS
 SELECT product_family_key,
    count(*) AS product_count,
    array_agg(drug_id ORDER BY drug_id) AS drug_ids
   FROM public.drug_products
  WHERE (product_family_key IS NOT NULL)
  GROUP BY product_family_key;


--
-- Name: v_drug_name_duplicates; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_drug_name_duplicates AS
 SELECT normalized_name_en,
    count(*) AS product_count,
    array_agg(drug_id ORDER BY drug_id) AS drug_ids
   FROM public.drug_products
  WHERE (normalized_name_en IS NOT NULL)
  GROUP BY normalized_name_en
 HAVING (count(*) > 1);


--
-- Name: v_weight_total; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_weight_total AS
 SELECT COALESCE(sum(weight), (0)::numeric) AS total_weight
   FROM public.matching_weights;


--
-- Name: dosage_form_aliases alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dosage_form_aliases ALTER COLUMN alias_id SET DEFAULT nextval('public.dosage_form_aliases_alias_id_seq'::regclass);


--
-- Name: drug_aliases alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_aliases ALTER COLUMN alias_id SET DEFAULT nextval('public.drug_aliases_alias_id_seq'::regclass);


--
-- Name: drug_barcodes barcode_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_barcodes ALTER COLUMN barcode_id SET DEFAULT nextval('public.drug_barcodes_barcode_id_seq'::regclass);


--
-- Name: drug_ingredients drug_ingredient_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_ingredients ALTER COLUMN drug_ingredient_id SET DEFAULT nextval('public.drug_ingredients_drug_ingredient_id_seq'::regclass);


--
-- Name: drug_products drug_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_products ALTER COLUMN drug_id SET DEFAULT nextval('public.drug_products_drug_id_seq'::regclass);


--
-- Name: import_issues issue_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues ALTER COLUMN issue_id SET DEFAULT nextval('public.import_issues_issue_id_seq'::regclass);


--
-- Name: import_runs import_run_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_runs ALTER COLUMN import_run_id SET DEFAULT nextval('public.import_runs_import_run_id_seq'::regclass);


--
-- Name: ingredient_aliases alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_aliases ALTER COLUMN alias_id SET DEFAULT nextval('public.ingredient_aliases_alias_id_seq'::regclass);


--
-- Name: manufacturer_aliases alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturer_aliases ALTER COLUMN alias_id SET DEFAULT nextval('public.manufacturer_aliases_alias_id_seq'::regclass);


--
-- Name: normalization_aliases alias_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.normalization_aliases ALTER COLUMN alias_id SET DEFAULT nextval('public.normalization_aliases_alias_id_seq'::regclass);


--
-- Data for Name: dosage_form_aliases; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.dosage_form_aliases (alias_id, alias, normalized_alias, dosage_form_code, canonical_en, canonical_zh, release_type, source) FROM stdin;
1	tab	tab	tablet	tablet	錠劑	\N	manual
2	tabs	tabs	tablet	tablet	錠劑	\N	manual
3	tablet	tablet	tablet	tablet	錠劑	\N	manual
4	tablets	tablets	tablet	tablet	錠劑	\N	manual
5	cap	cap	capsule	capsule	膠囊	\N	manual
6	capsule	capsule	capsule	capsule	膠囊	\N	manual
7	f.c.	f.c.	film-coated tablet	film-coated tablet	膜衣錠	\N	manual
8	fc	fc	film-coated tablet	film-coated tablet	膜衣錠	\N	manual
9	enteric-coated tablet	enteric-coated tablet	enteric-coated tablet	enteric-coated tablet	腸溶錠	\N	manual
10	effervescent tablet	effervescent tablet	effervescent tablet	effervescent tablet	發泡錠	\N	manual
11	granules	granules	granules	granules	顆粒劑	\N	manual
12	suppository	suppository	suppository	suppository	栓劑	\N	manual
13	xr	xr	tablet	tablet	錠劑	extended-release	manual
14	er	er	tablet	tablet	錠劑	extended-release	manual
15	sr	sr	tablet	tablet	錠劑	sustained-release	manual
\.


--
-- Data for Name: drug_aliases; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.drug_aliases (alias_id, drug_id, alias, normalized_alias, language_code, alias_type) FROM stdin;
\.


--
-- Data for Name: drug_barcodes; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.drug_barcodes (barcode_id, drug_id, barcode, barcode_type) FROM stdin;
1	1	4719879910032	EAN-13
2	2	4716140000904	EAN-13
3	3	4716140060311	EAN-13
4	4	4713930037690	EAN-13
5	5	4710836252622	EAN-13
6	8	4715689436663	EAN-13
7	13	4715126419532	EAN-13
8	18	4716140403101	EAN-13
9	23	471969383916	EAN-13
10	30	4716140406454	EAN-13
11	33	471916017339	EAN-13
12	35	4716140213205	EAN-13
13	42	4710993908240	EAN-13
14	45	8711141910319	EAN-13
15	46	(01)04716675467869	EAN-13
16	47	(01)04716675467876	EAN-13
17	48	(01)04716675148775	EAN-13
18	53	(01)04716675101565	EAN-13
19	55	4719858943822	EAN-13
20	59	4715689444514	EAN-13
21	70	4710596702993	EAN-13
24	77	4711396000531	EAN-13
25	78	4711396000562	EAN-13
26	81	4716140229008	EAN-13
27	85	105060856790734	EAN-13
28	86	4713680322909	EAN-13
29	87	4719866940660	EAN-13
30	88	471504530139	EAN-13
31	93	4716140063008	EAN-13
32	99	471589883047	EAN-13
33	102	4710836252769	EAN-13
34	105	4716140213502	EAN-13
35	106	4719858941187	EAN-13
36	107	4719873510214	EAN-13
37	111	104711144715304	EAN-13
38	112	5000456012010	EAN-13
39	119	4711916011009	EAN-13
22	71	4711396332489	EAN-13
23	72	4711396332472	EAN-13
\.


--
-- Data for Name: drug_ingredients; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.drug_ingredients (drug_ingredient_id, drug_id, ingredient_order, ingredient_raw, ingredient_normalized, language_code) FROM stdin;
1	1	1	Acetaminophen	acetaminophen	en
2	2	1	Acetylcysteine	acetylcysteine	en
3	3	1	Acetylcysteine	acetylcysteine	en
4	4	1	Thiamine	thiamine	en
5	4	2	Riboflavin	riboflavin	en
6	4	3	Pyridoxine	pyridoxine	en
7	4	4	Cyanocobalamin	cyanocobalamin	en
8	5	1	Alginic acid	alginic acid	en
9	5	2	Magnesium carbonate	magnesium carbonate	en
10	5	3	Aluminum hydroxide	aluminum hydroxide	en
162	244	1	Glimepiride	glimepiride	en
163	244	2	Metformin HCl	metformin hcl	en
13	7	1	Glycyrrhetic acid	glycyrrhetic acid	en
14	7	2	Benzocaine	benzocaine	en
15	7	3	Lidocaine	lidocaine	en
16	7	4	Phenylephrine HCl	phenylephrine hcl	en
17	7	5	Bismuth subnitrate	bismuth subnitrate	en
18	7	6	Chlorhexidine acetate	chlorhexidine acetate	en
19	8	1	Aspirin	aspirin	en
20	9	1	Nifedipine	nifedipine	en
172	248	1	Ezetimibe	ezetimibe	en
173	248	2	Atorvastatin	atorvastatin	en
23	11	1	Azithromycin	azithromycin	en
24	12	1	Sulfamethoxazole	sulfamethoxazole	en
25	12	2	Trimethoprim	trimethoprim	en
26	13	1	Silymarin	silymarin	en
27	14	1	Bisacodyl	bisacodyl	en
28	15	1	Bisacodyl	bisacodyl	en
29	16	1	Nefopam	nefopam	en
30	17	1	Propranolol	propranolol	en
31	18	1	Diltiazem Hydrochloride	diltiazem hydrochloride	en
183	257	1	Cefadroxil	cefadroxil	en
33	20	1	Valsartan	valsartan	en
34	20	2	Hydrochlorothiazide	hydrochlorothiazide	en
35	21	1	Bisoprolol	bisoprolol	en
187	260	1	Rosuvastatin	rosuvastatin	en
37	23	1	Acarbose	acarbose	en
38	24	1	Acetaminophen	acetaminophen	en
39	25	1	Pancreatin	pancreatin	en
40	25	2	Metoclopramide HCl	metoclopramide hcl	en
41	26	1	Diphenidol HCl	diphenidol hcl	en
42	27	1	Domperidone	domperidone	en
134	103	1	Tegafur	tegafur	en
43	28	1	Doxazosin	doxazosin	en
44	29	1	Venlafaxine HCl	venlafaxine hcl	en
45	30	1	Benzbromarone	benzbromarone	en
46	31	1	Estazolam	estazolam	en
47	32	1	Rivastigmine	rivastigmine	en
48	33	1	Famotidine	famotidine	en
49	34	1	Famotidine	famotidine	en
50	35	1	Cyclobenzaprine HCl	cyclobenzaprine hcl	en
51	36	1	Acetylcysteine	acetylcysteine	en
52	37	1	Macrogol 4000	macrogol 4000	en
53	38	1	Dimethicone	dimethicone	en
54	39	1	Ginkgoflavonglycosides	ginkgoflavonglycosides	en
55	40	1	Pioglitazone	pioglitazone	en
56	41	1	Metformin HCl	metformin hcl	en
57	42	1	Mitiglinide calcium hydrate	mitiglinide calcium hydrate	en
58	43	1	Metamagnesium aluminosilicate	metamagnesium aluminosilicate	en
59	43	2	Dihydroxyaluminum allantoinate	dihydroxyaluminum allantoinate	en
60	44	1	Losartan potassium	losartan potassium	en
61	44	2	Hydrochlorothiazide	hydrochlorothiazide	en
62	45	1	Sitagliptin	sitagliptin	en
63	45	2	Metformin HCl	metformin hcl	en
64	46	1	Empagliflozin	empagliflozin	en
65	47	1	Empagliflozin	empagliflozin	en
66	48	1	Empagliflozin	empagliflozin	en
67	48	2	Metformin HCl	metformin hcl	en
68	49	1	Calcium polystyrene sulfonate	calcium polystyrene sulfonate	en
69	50	1	Dimethylpolysiloxane	dimethylpolysiloxane	en
70	51	1	Thiamine	thiamine	en
71	51	2	Pyridoxine	pyridoxine	en
72	51	3	Cyanocobalamin	cyanocobalamin	en
73	52	1	Lorazepam	lorazepam	en
74	53	1	Brotizolam	brotizolam	en
75	54	1	Fenofibrate Micronized	fenofibrate micronized	en
76	55	1	Loperamide HCl	loperamide hcl	en
77	56	1	Trazodone HCl	trazodone hcl	en
78	57	1	Dextromethorphan HBr	dextromethorphan hbr	en
79	57	2	Potassium cresolsulfonate	potassium cresolsulfonate	en
80	57	3	Lysozyme chloride	lysozyme chloride	en
81	58	1	Megestrol acetate	megestrol acetate	en
82	59	1	Diclofenac potassium	diclofenac potassium	en
234	298	1	Magnesium oxide	magnesium oxide	en
84	61	1	Mirtazapine	mirtazapine	en
236	300	1	Phenprobamate	phenprobamate	en
86	63	1	Meloxicam	meloxicam	en
87	64	1	Mosapride citrate	mosapride citrate	en
88	65	1	Mosapride citrate	mosapride citrate	en
89	66	1	Naproxen	naproxen	en
241	305	1	Tamoxifen	tamoxifen	en
91	68	1	Vildagliptin	vildagliptin	en
92	68	2	Metformin HCl	metformin hcl	en
93	69	1	Olmesartan	olmesartan	en
94	70	1	Amlodipine,Olmesartan	amlodipine,olmesartan	en
95	71	1	Aripiprazole	aripiprazole	en
96	72	1	Aripiprazole	aripiprazole	en
248	311	1	Oxycodone HCl	oxycodone hcl	en
98	74	1	Phenytoin	phenytoin	en
99	75	1	Prednisolone	prednisolone	en
100	76	1	Propranolol HCl	propranolol hcl	en
101	77	1	Brexpiprazole	brexpiprazole	en
102	78	1	Brexpiprazole	brexpiprazole	en
103	79	1	Clonazepam	clonazepam	en
104	80	1	Clonazepam	clonazepam	en
105	81	1	Dextromethorphan HBr	dextromethorphan hbr	en
106	81	2	Potassium cresolsulfonate	potassium cresolsulfonate	en
107	81	3	Lysozyme chloride	lysozyme chloride	en
108	82	1	Propafenone HCl	propafenone hcl	en
109	83	1	Sennosides	sennosides	en
110	84	1	Quetiapine fumarate	quetiapine fumarate	en
111	85	1	Quetiapine fumarate	quetiapine fumarate	en
112	86	1	Paroxetine	paroxetine	en
113	87	1	Olmesartan medoxomil	olmesartan medoxomil	en
114	87	2	Amlodipine	amlodipine	en
115	88	1	Chlorzoxazone	chlorzoxazone	en
116	88	2	Acetaminophen	acetaminophen	en
117	89	1	Acetaminophen	acetaminophen	en
118	89	2	Chlorzoxazone	chlorzoxazone	en
119	89	3	Caffeine	caffeine	en
120	89	4	Thiamine disulfide	thiamine disulfide	en
121	90	1	Spironolactone	spironolactone	en
122	91	1	Hydralazine	hydralazine	en
123	92	1	Oxethazaine	oxethazaine	en
124	92	2	Polymigel	polymigel	en
125	93	1	Piracetam	piracetam	en
126	94	1	Carvedilol	carvedilol	en
127	95	1	Tamsulosin hydrochloride	tamsulosin hydrochloride	en
128	96	1	Tamsulosin HCl	tamsulosin hcl	en
129	97	1	Tetracycline HCl	tetracycline hcl	en
130	98	1	Theophylline anhydrous	theophylline anhydrous	en
131	99	1	Clopidogrel	clopidogrel	en
132	100	1	Sennoside	sennoside	en
133	102	1	Tribasic calcium phosphate	tribasic calcium phosphate	en
135	103	2	Uracil	uracil	en
136	104	1	Famotidine	famotidine	en
137	105	1	Silodosin	silodosin	en
138	106	1	Ursodeoxycholic acid	ursodeoxycholic acid	en
139	107	1	Quetiapine	quetiapine	en
291	346	1	Voriconazole	voriconazole	en
141	109	1	Alprazolam	alprazolam	en
142	110	1	Alprazolam	alprazolam	en
143	111	1	Rivaroxaban	rivaroxaban	en
144	112	1	Dapagliflozin	dapagliflozin	en
145	112	2	Metformin HCl	metformin hcl	en
146	113	1	Levocetirizine dihydrochloride	levocetirizine dihydrochloride	en
147	114	1	Levocetirizine dihydrochloride	levocetirizine dihydrochloride	en
148	115	1	Etoricoxib	etoricoxib	en
300	354	1	Lercanidipine HCl	lercanidipine hcl	en
301	356	1	Sertraline	sertraline	en
151	119	1	Zopiclone	zopiclone	en
\.


--
-- Data for Name: drug_products; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.drug_products (drug_id, source_record_key, identity_key_type, folder_name, drug_name_en, drug_name_zh, normalized_name_en, normalized_name_zh, product_family_key, strength_raw, strength_normalized, dosage_form_en, dosage_form_zh, dosage_form_code, release_type, license_kind, license_number, manufacturer_en, manufacturer_zh, source_row_number, import_run_id, created_at, updated_at) FROM stdin;
244	COMPOSITE_EN:91a87d2a851c33fdcb280e07b31989c8d0e2556172c541eb520ae26246888911	COMPOSITE_EN	Amamet F.C. Tablets 500mg	Amamet	愛糖降	amamet	愛糖降	EN:amamet	2/500mg	500mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	\N	正和	7	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
248	COMPOSITE_EN:8d67e03c2526a93df25d19812f8c03e15caf65953357435d837cde9764f2de63	COMPOSITE_EN	ATOZET	ATOZET	優泰脂	atozet	優泰脂	EN:atozet	10/20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	ORGANON	\N	11	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
13	LICENSE:製:041952	LICENSE	Bao-gan Capsules 150mg	Bao-gan	保肝勇	bao-gan	保肝勇	EN:bao-gan	150mg	150mg	Capsule	膠囊	capsule	\N	製	041952	Chen Ta	成大	14	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
14	LICENSE:製:09250	LICENSE	Bisacodyl 10mg	Bisacodyl	永信無秘	bisacodyl	永信無秘	EN:bisacodyl	10mg	10mg	Suppository	栓劑	suppository	\N	製	09250	\N	永信	15	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
15	LICENSE:製:018949	LICENSE	Bisacodyl enteric FCT	Bisacodyl	秘克的	bisacodyl	秘克的	EN:bisacodyl	5mg	5mg	Enteric-coated Tablet	腸溶錠	enteric-coated tablet	\N	製	018949	VPC	榮民	16	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
16	LICENSE:製:26272	LICENSE	Capain F.C. Tab Nefopam 30mg	Capain	痛定	capain	痛定	EN:capain	30mg	30mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	26272	\N	永信	17	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
17	LICENSE:製:023037	LICENSE	Cardolol Tablets 10mg	Cardolol	心康樂	cardolol	心康樂	EN:cardolol	10mg	10mg	Tablet	錠劑	tablet	\N	製	023037	\N	榮民	18	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
18	LICENSE:製:036966	LICENSE	Cartil Tablets Diltiazem Hydrochloride 30mg	Cartil	卡迪爾	cartil	卡迪爾	EN:cartil	30mg	30mg	Tablets	錠劑	tablet	\N	製	036966	\N	健喬	19	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
20	LICENSE:輸:023109	LICENSE	Co-Diovan	Co-Diovan	可得安穩	co-diovan	可得安穩	EN:co-diovan	80/12.5	\N	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	023109	NOVARTIS FARMA S.p.A.	\N	21	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
21	LICENSE:輸:017125	LICENSE	Concor 5mg	Concor	康肯	concor	康肯	EN:concor	5mg	5mg	Tablet	錠劑	tablet	\N	輸	017125	Merck Healthcare KGaA	默克	22	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
260	COMPOSITE_EN:e0d2102a495b3814ea4e5ecd37ac4ee8939233fb64dc803c7fd50d51bf0435a2	COMPOSITE_EN	CRESTOR	CRESTOR	冠脂妥	crestor	冠脂妥	EN:crestor	10mg	10mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	ASTRAZENECA	\N	23	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
23	LICENSE:製:045646	LICENSE	Deglu	Deglu	抵克醣	deglu	抵克醣	EN:deglu	50mg	50mg	Tablet	錠	tablet	\N	製	045646	Lotus	美時	24	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
24	LICENSE:製:020707	LICENSE	Depyretin 500mg	Depyretin	得百利寧	depyretin	得百利寧	EN:depyretin	500mg	500mg	Tablet	錠劑	tablet	\N	製	020707	\N	榮民	25	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
25	LICENSE:製:046351	LICENSE	DIMOTIL	DIMOTIL	立消樂	dimotil	立消樂	EN:dimotil	212.5mg/5mg	212.5mg/5mg	Tablet	錠劑	tablet	\N	製	046351	\N	明德	26	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
26	LICENSE:製:015078	LICENSE	Diphenidol HCI 25mg	Diphenidol HCl	敵芬尼朵	diphenidol hcl	敵芬尼朵	EN:diphenidol hcl	25mg	25mg	S.C TAB.	糖衣錠	tablet	\N	製	015078	\N	生達	27	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
27	LICENSE:製:047310	LICENSE	Domtoo	Domtoo	除胃障	domtoo	除胃障	EN:domtoo	10mg	10mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	047310	\N	生達	28	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
28	LICENSE:製:023711	LICENSE	DOXABEN XL Tablets 4mg	DOXABEN XL	可迅	doxaben xl	可迅	EN:doxaben xl	4mg	4mg	Extended-release Tablet	持續性藥效錠	tablet	extended-release	製	023711	VIATRIS	\N	29	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
29	COMPOSITE_EN:b2192ef7cfe07454ac811e9d722655c98ac59e2211cf7c63c78fcb16de49b374	COMPOSITE_EN	EFFEXOR XR 37.5mg	EFFEXOR XR	速悅	effexor xr	速悅	EN:effexor xr	37.5mg	37.5mg	Extended-release Capsule	持續性藥效膠囊	capsule	extended-release	\N	\N	VIATRIS	暉致	30	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
30	LICENSE:製:042754	LICENSE	Euricon Tablets 50mg	Euricon	優力康	euricon	優力康	EN:euricon	50mg	50mg	Tablet	錠劑	tablet	\N	製	042754	\N	健喬	31	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
31	LICENSE:製:012458	LICENSE	EURODIN 2mg	EURODIN	悠樂丁	eurodin	悠樂丁	EN:eurodin	2mg	2mg	Tablet	錠劑	tablet	\N	製	012458	\N	武田	32	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
32	LICENSE:輸:022861	LICENSE	Exelon	Exelon	憶思能	exelon	憶思能	EN:exelon	1.5mg	1.5mg	Capsule	膠囊	capsule	\N	輸	022861	\N	\N	33	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
33	LICENSE:製:042863	LICENSE	FAMO F.C. Tablets 20mg	FAMO	發馬	famo	發馬	EN:famo	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	042863	\N	信東	34	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
34	LICENSE:製:057791	LICENSE	Famotidine F.C. Tablets 20mg	Famotidine	法瑪鎮	famotidine	法瑪鎮	EN:famotidine	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	057791	CYH	中化裕民	35	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
35	LICENSE:製:058755	LICENSE	Flexer Extended-Release F.C. Tablets 15mg	Flexer Extended-Release	服樂適	flexer extended-release	服樂適	EN:flexer extended-release	15mg	15mg	Extended-release Film-coated Tablet	持續性釋放膜衣錠	film-coated tablet	extended-release	製	058755	\N	健喬	36	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
36	LICENSE:製:030873	LICENSE	Flutafin Capsule 200mg	Flutafin	化痰能	flutafin	化痰能	EN:flutafin	200mg	200mg	Capsule	膠囊	capsule	\N	製	030873	Shiteh	西德有機	37	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
37	LICENSE:輸:023462	LICENSE	forlax 10mg	Forlax	化痰能	forlax	化痰能	EN:forlax	10g	10000mg	Powder for Oral Suspension	口服懸液用粉劑	powder for oral suspension	\N	輸	023462	\N	大昌華嘉	38	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
38	LICENSE:製:000415	LICENSE	Gasmin 40mg	Gasmin	瓦斯敏	gasmin	瓦斯敏	EN:gasmin	40mg	40mg	Tablet	錠劑	tablet	\N	製	000415	\N	福元	39	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
39	LICENSE:製:032642	LICENSE	Giko film-coated Tablets	Giko	循克	giko	循克	EN:giko	9.6mg	9.6mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	032642	H.S.	黃氏	40	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
40	LICENSE:製:049930	LICENSE	Glitis 30mg	Glitis	泌特穩	glitis	泌特穩	EN:glitis	30mg	30mg	Tablet	錠劑	tablet	\N	製	049930	\N	中國化學	41	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
41	LICENSE:製:FR2584250	LICENSE	Glucophage	Glucophage	庫魯化	glucophage	庫魯化	EN:glucophage	500mg	500mg	Tablet	錠劑	tablet	\N	製	FR2584250	\N	\N	42	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
42	LICENSE:製:052337	LICENSE	Glufast Tablet 10mg	Glufast	快如妥	glufast	快如妥	EN:glufast	10mg	10mg	Tablet	錠劑	tablet	\N	製	052337	\N	友載生技險集股份有限公司	43	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
43	LICENSE:製:044977	LICENSE	GoweLL	Gowell	固胃	gowell	固胃	EN:gowell	450mg/50mg	450mg/50mg	Tablet	錠劑	tablet	\N	製	044977	Wecam	惠勝	44	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
44	LICENSE:輸:024643	LICENSE	HYZAAR 100	HYZAAR	好悅您	hyzaar	好悅您	EN:hyzaar	100mg/12.5mg	100mg/12.5mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	024643	ORGANON	\N	45	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
45	BARCODE:8711141910319	BARCODE	Janumet 50	Janumet	捷糖穩	janumet	捷糖穩	EN:janumet	50/850mg	850mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	MSD	\N	46	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
46	BARCODE:(01)04716675467869	BARCODE	Jardiance 10mg	Jardiance	恩排糖	jardiance	恩排糖	EN:jardiance	10mg	10mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	Boehringer Ingelheim	\N	47	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
47	BARCODE:(01)04716675467876	BARCODE	Jardiance 25mg	Jardiance	恩排糖	jardiance	恩排糖	EN:jardiance	25mg	25mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	Boehringer Ingelheim	\N	48	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
48	BARCODE:(01)04716675148775	BARCODE	Jardiance Duo	Jardiance Duo	恩美糖	jardiance duo	恩美糖	EN:jardiance duo	12.5/850mg	850mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	\N	\N	49	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
49	LICENSE:製:013086	LICENSE	KALIMATE	KALIMATE	加利美粉	kalimate	加利美粉	EN:kalimate	\N	\N	Powder	散劑	powder	\N	製	013086	KOWA	\N	50	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
50	LICENSE:製:029828	LICENSE	Kascoal Tab. 400mg	Kascoal	加斯克兒	kascoal	加斯克兒	EN:kascoal	40mg	40mg	Tablet	錠劑	tablet	\N	製	029828	\N	永信	51	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
51	LICENSE:製:014025	LICENSE	Kentamin Cap	Kentamin	開恩達命	kentamin	開恩達命	EN:kentamin	50mg/50mg/500mcg	50mg/50mg/0.5mg	Capsule	膠囊	capsule	\N	製	014025	\N	寶齡富錦	52	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
52	LICENSE:製:033929	LICENSE	Larpam	Larpam	樂眠	larpam	樂眠	EN:larpam	2mg	2mg	Tablet	錠劑	tablet	\N	製	033929	Chen Ta	成大	53	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
53	LICENSE:製:025713	LICENSE	Lendormin 0.25mg	Lendormin	戀多眠	lendormin	戀多眠	EN:lendormin	0.25mg	0.25mg	Tablet	錠劑	tablet	\N	製	025713	Boehringer Ingelheim	百靈佳	54	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
54	LICENSE:製:049551	LICENSE	LINLIP	LINLIP	去脂醇微粒化囊	linlip	去脂醇微粒化囊	EN:linlip	200mg	200mg	Capsule	膠囊	capsule	\N	製	049551	Chinteng	井田	55	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
55	LICENSE:製:020059	LICENSE	LOPERAM 2mg	LOPERAM	肚倍朗	loperam	肚倍朗	EN:loperam	2mg	2mg	Capsule	膠囊	capsule	\N	製	020059	\N	強生	56	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
56	LICENSE:製:033664	LICENSE	Mesyrel	Mesyrel	美舒鬱	mesyrel	美舒鬱	EN:mesyrel	50mg	50mg	Tablet	錠劑	tablet	\N	製	033664	Lotus	美時	57	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
57	LICENSE:製:021758	LICENSE	Medicon-A_Capsules	Medicon-A	滅咳康複合	medicon-a	滅咳康複合	EN:medicon-a	20mg/90mg/20mg	20mg/90mg/20mg	Capsule	膠囊	capsule	\N	製	021758	\N	鹽野義	58	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
58	LICENSE:製:048182	LICENSE	Megejohn	Megejohn	美雅祥	megejohn	美雅祥	EN:megejohn	160mg	160mg	TAB.	錠	tablet	\N	製	048182	\N	健喬	59	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
59	LICENSE:製:044450	LICENSE	MEITAN F.C. Tablets 25mg	MEITAN	漠疼	meitan	漠疼	EN:meitan	25mg	25mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	044450	\N	永勝	60	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
298	COMPOSITE_EN:a33b64a2fd886f1869d7427b3adddce7be5c5aede0426281caf35cc51999c555	COMPOSITE_EN	MgO 250mg	MgO	\N	mgo	\N	EN:mgo	250mg	250mg	\N	\N	\N	\N	\N	\N	\N	\N	61	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
61	LICENSE:製:049078	LICENSE	Mirzapine F.C. Tablets 30mg	Mirzapine	莫憂平	mirzapine	莫憂平	EN:mirzapine	30mg	30mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	049078	健喬	\N	62	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
300	COMPOSITE_EN:1977327588f2b468d9270fd90b28c91ca098e764dc5e5f58136d86457eef3f07	COMPOSITE_EN	Mocolax 400mg	Mocolax	肌緩痛	mocolax	肌緩痛	EN:mocolax	400mg	400mg	Tablet	錠劑	tablet	\N	\N	\N	\N	元宙	63	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
63	LICENSE:製:049146	LICENSE	Mopik Tablets 15mg	Mopik	莫比克	mopik	莫比克	EN:mopik	15mg	15mg	Tablet	錠劑	tablet	\N	製	049146	N.K.	南光	64	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
64	LICENSE:製:055564	LICENSE	Mosad Tablets 5mg	Mosad	胃莫傷	mosad	胃莫傷	EN:mosad	5mg	5mg	Tablet	錠劑	tablet	\N	製	055564	\N	五洲	65	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
65	COMPOSITE_EN:86d5d132deb16458f987e2baa6a42b24963747246c5c5e32cf8c6d62e639e420	COMPOSITE_EN	Mosapride Citrate 5mg	Mosapride Citrate	摩舒胃清	mosapride citrate	摩舒胃清	EN:mosapride citrate	5mg	5mg	TABLET	膜衣錠	tablet	\N	\N	\N	\N	東洋	66	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
66	LICENSE:製:019620	LICENSE	NAPROXEN 250mg	Naproxen	那普洛先	naproxen	那普洛先	EN:naproxen	250mg	250mg	Tablet	錠劑	tablet	\N	製	019620	Sinphar	杏輝	67	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
305	COMPOSITE_EN:1a4e9393e499931ecffa27ee3eb97d5fc913f88c0402ddba51199e090880f853	COMPOSITE_EN	Nolvadex Tamoxifen 10mg	Nolvadex	\N	nolvadex	\N	EN:nolvadex	10mg	10mg	Tablet	錠劑	tablet	\N	\N	\N	\N	\N	68	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
68	LICENSE:輸:025481	LICENSE	NOVARTIS Galvus Met 50	Galvus Met	高糖優美	galvus met	高糖優美	EN:galvus met	50/850mg	850mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	025481	NOVARTIS	\N	69	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
69	LICENSE:製:057234	LICENSE	Olsaa F.C.Tablets 20mg	Olsaa	優穩壓	olsaa	優穩壓	EN:olsaa	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	057234	\N	中國化學	70	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
70	LICENSE:製:061466	LICENSE	OlsaaCa Tablets 40mg	OlsaaCa	双優惠脈	olsaaca	双優惠脈	EN:olsaaca	5/40mg	40mg	Tablets	錠劑	tablet	\N	製	061466	\N	中國化學	71	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
71	LICENSE:輸:024048	LICENSE	Otsuka Abilify 15mg	Abilify	安立復	abilify	安立復	EN:abilify	15mg	15mg	Tablet	錠劑	tablet	\N	輸	024048	Otsuka	大塚	72	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
72	LICENSE:輸:024046	LICENSE	Otsuka Abilify 5mg	Abilify	安立復	abilify	安立復	EN:abilify	5mg	5mg	Tablet	錠劑	tablet	\N	輸	024046	Otsuka	大塚	73	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
311	COMPOSITE_EN:c1fe2fe65b30b56a0a16b76e9d7dfedc57a1db2b2ac95f7454ed4a9872192fa6	COMPOSITE_EN	OxyContin	OxyContin	疼始康定	oxycontin	疼始康定	EN:oxycontin	10mg	10mg	Controlled-release Tablet	持續藥效錠	tablet	\N	\N	\N	\N	\N	74	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
74	LICENSE:製:018240	LICENSE	Phenytoin Tablets 100mg	Phenytoin	苯乙內醯脲	phenytoin	苯乙內醯脲	EN:phenytoin	100mg	100mg	Tablet	錠劑	tablet	\N	製	018240	VPC	榮民	75	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
75	LICENSE:製:003365	LICENSE	Prednisolone Tablets 5mg	Prednisolone	去氫可體醇	prednisolone	去氫可體醇	EN:prednisolone	5mg	5mg	Tablet	錠劑	tablet	\N	製	003365	VPC	榮民	76	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
76	LICENSE:製:009102	LICENSE	Propranolol HCI 10mg	Propranolol HCl	\N	propranolol hcl	\N	EN:propranolol hcl	10mg	10mg	Tablet	錠劑	tablet	\N	製	009102	\N	生達	77	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
77	LICENSE:輸:027365	LICENSE	REXULTI 1mg	REXULTI	銳思定	rexulti	銳思定	EN:rexulti	1mg	1mg	Tablet	膜衣錠	tablet	\N	輸	027365	Otsuka	大塚	78	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
78	LICENSE:輸:027368	LICENSE	REXULTI 4mg	REXULTI	銳思定	rexulti	銳思定	EN:rexulti	4mg	4mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	027368	Otsuka	大塚	79	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
79	LICENSE:製:058135	LICENSE	Ripam Tablets 2mg	Ripam	利平靜	ripam	利平靜	EN:ripam	2mg	2mg	Tablet	錠劑	tablet	\N	製	058135	\N	中生	80	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
80	LICENSE:輸:003078	LICENSE	Rivotril	Rivotril	利福全	rivotril	利福全	EN:rivotril	2mg	2mg	Tablet	錠劑	tablet	\N	輸	003078	\N	\N	81	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
81	LICENSE:製:038819	LICENSE	ROMICON-A	ROMICON-A	樂滅咳	romicon-a	樂滅咳	EN:romicon-a	\N	\N	Capsule	複方膠囊	capsule	\N	製	038819	\N	健喬	82	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
82	LICENSE:輸:019918	LICENSE	Rytmononm 150mg	Rytmonorm	心利正	rytmonorm	心利正	EN:rytmonorm	150mg	150mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	019918	\N	\N	83	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
83	COMPOSITE_EN:a3cc78710a7bae8166089bad509eedca647fe7bb8a861ed2e86af78b7e72b7e3	COMPOSITE_EN	Senokot	Senokot	\N	senokot	\N	EN:senokot	\N	\N	\N	\N	\N	\N	\N	\N	\N	\N	84	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
84	COMPOSITE_EN:9651c6f3e721d6a03aca7e3e1d3ed2f67a9017ea602654ffa9797f30ac2e0223	COMPOSITE_EN	Seroquel 25mg	Seroquel	思樂康	seroquel	思樂康	EN:seroquel	25mg	25mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	\N	\N	85	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
85	BARCODE:105060856790734	BARCODE	Seroquel XR 50mg	Seroquel XR	思樂康	seroquel xr	思樂康	EN:seroquel xr	50mg	50mg	Prolonged-release Tablet	持續性藥效錠	tablet	extended-release	\N	\N	\N	\N	86	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
86	LICENSE:製:044622	LICENSE	Setine F.C. Tablets 20mg	Setine	除憂定	setine	除憂定	EN:setine	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	044622	\N	生達	87	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
87	BARCODE:4719866940660	BARCODE	Sevikar 20mg	Sevikar	舒脈康	sevikar	舒脈康	EN:sevikar	5/20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	Daiichi-Sankyo	\N	88	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
88	LICENSE:製:011012	LICENSE	Sketa Capsules	Sketa	弛刻達	sketa	弛刻達	EN:sketa	\N	\N	Capsule	膠囊	capsule	\N	製	011012	PATRON	派頓	89	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
89	LICENSE:製:036749	LICENSE	SOMA Cap	SOMA	舒肌痛	soma	舒肌痛	EN:soma	250mg/150mg/20mg/7.7mg	250mg/150mg/20mg/7.7mg	Capsule	膠囊	capsule	\N	製	036749	\N	生達	90	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
90	LICENSE:製:012081	LICENSE	Spiron Tablets Spironolactone 25mg	Spiron	輸泌來	spiron	輸泌來	EN:spiron	25mg	25mg	Tablet	錠劑	tablet	\N	製	012081	\N	約克	91	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
91	LICENSE:製:031540	LICENSE	Stable Tabs 10mg	Stable	血得平	stable	血得平	EN:stable	10mg	10mg	Tabs	錠劑	tabs	\N	製	031540	\N	榮民	92	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
92	LICENSE:製:005811	LICENSE	Strocain	Strocain	息痛佳音	strocain	息痛佳音	EN:strocain	5mg/244mg	5mg/244mg	Tablet	錠劑	tablet	\N	製	005811	Eisai	衛采	93	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
93	LICENSE:製:048727	LICENSE	Syntam 2400mg	Syntam	郝智	syntam	郝智	EN:syntam	2400mg	2400mg	Oral Granules	內服溶液用顆粒劑	granules	\N	製	048727	\N	健喬	94	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
94	LICENSE:製:046699	LICENSE	Syntrend Tablets 6.25mg	Syntrend	心全	syntrend	心全	EN:syntrend	6.25mg	6.25mg	Tablet	錠劑	tablet	\N	製	046699	\N	健喬	95	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
95	LICENSE:製:046016	LICENSE	Tamlosin Tamsulosin hydrochloride 0.2mg	Tamlosin	暢利淨	tamlosin	暢利淨	EN:tamlosin	0.2mg	0.2mg	Sustained-release Capsule	持續性釋放膠囊	capsule	sustained-release	製	046016	\N	生達	96	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
96	LICENSE:製:047629	LICENSE	Tamso_SR	Tamso SR	替你坦舒持續性釋放	tamso sr	替你坦舒持續性釋放	EN:tamso sr	0.2mg	0.2mg	Sustained-release Capsule	持續性釋放膠囊	capsule	sustained-release	製	047629	\N	五洲	97	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
97	LICENSE:製:015791	LICENSE	Tetracycline_HCI_250mg	Tetracycline HCl	\N	tetracycline hcl	\N	EN:tetracycline hcl	250mg	250mg	CAPsule	膠囊	capsule	\N	製	015791	VPC	榮民	98	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
98	LICENSE:製:044924	LICENSE	Theophyline anhydrous	THOIN S.R.M.C.	喘克	thoin s.r.m.c.	喘克	EN:thoin s.r.m.c.	125mg	125mg	\N	緩釋微粒膠囊	緩釋微粒膠囊	\N	製	044924	\N	永勝	99	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
99	LICENSE:製:048730	LICENSE	Thrombifree Clopidogrel 75mg	Thrombifree	健克栓	thrombifree	健克栓	EN:thrombifree	75mg	75mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	048730	\N	健維	100	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
100	LICENSE:製:037697	LICENSE	Through 20mg	Through	便通樂	through	便通樂	EN:through	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	037697	\N	中美兄弟	101	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
101	COMPOSITE_EN:022f909cb93cfde0aa853d0c2cce99fdc1f29812ea340f4b34b9296cab043cac	COMPOSITE_EN	TIMING	TIMING	憶智力	timing	憶智力	EN:timing	\N	\N	\N	\N	\N	\N	\N	\N	\N	天明	102	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
102	LICENSE:製:058237	LICENSE	Tribasic calcium phosphate 1203mg	Tribasic calcium phosphate	滋骨	tribasic calcium phosphate	滋骨	EN:tribasic calcium phosphate	1203mg	1203mg	Chewable Tablet	加強咀嚼錠	tablet	\N	製	058237	\N	東洋	103	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
103	LICENSE:製:043698	LICENSE	UFUR Capsule	UFUR	友復	ufur	友復	EN:ufur	100mg/224mg	100mg/224mg	Capsule	膠囊	capsule	\N	製	043698	\N	東洋	104	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
104	LICENSE:製:041352	LICENSE	ULSTOP 20mg	ULSTOP	悅潰止	ulstop	悅潰止	EN:ulstop	20mg	20mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	041352	\N	正和	105	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
105	LICENSE:製:058838	LICENSE	URIEF	URIEF	優列扶	urief	優列扶	EN:urief	4mg	4mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	058838	\N	健喬	106	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
106	BARCODE:4719858941187	BARCODE	UROSO Tablets 100mg	UROSO	利膽能	uroso	利膽能	EN:uroso	100mg	100mg	Tablet	錠劑	tablet	\N	\N	\N	\N	強生	107	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
107	LICENSE:製:049496	LICENSE	Utapine F.C. Tab. 100mg	Utapine	優達平	utapine	優達平	EN:utapine	100mg	100mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	049496	Union	寶瑞聯邦	108	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
346	COMPOSITE_EN:2e7c04a37c92b7b46e0400261c9a18aecc40dcf966971e54cfa434bc131e53e5	COMPOSITE_EN	Vfend F.c. Tablets 200mg	Vfend	黴飛膜	vfend	黴飛膜	EN:vfend	200mg	200mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	Pfizer	\N	109	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
109	COMPOSITE_EN:a05ebaeedec240691e9dbcf98646b0917fdaaaf302d6c78957c051f49bbb6abf	COMPOSITE_EN	XANAX 0.5mg	XANAX	贊安諾	xanax	贊安諾	EN:xanax	0.5mg	0.5mg	Tablet	錠劑	tablet	\N	\N	\N	VIATRIS	\N	110	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
110	COMPOSITE_EN:9e25ac75037afd7ee698df3205edafcc02f21eb182795eaee839f80b01b2cad2	COMPOSITE_EN	XANAX XR 0.5mg	XANAX XR	贊安諾	xanax xr	贊安諾	EN:xanax xr	0.5mg	0.5mg	Extended-release Tablet	持續性藥效錠	tablet	extended-release	\N	\N	VIATRIS	\N	111	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
1	LICENSE:製:032320	LICENSE	Acetal Tablet 500mg	Acetal	愛舒疼	acetal	愛舒疼	EN:acetal	500mg	500mg	Tablet	錠劑	tablet	\N	製	032320	PURZER	瑞安	2	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
2	LICENSE:製:045993	LICENSE	Actein Effervescent Tablets 600mg	Actein	愛克痰	actein	愛克痰	EN:actein	600mg	600mg	Effervescent Tablet	發泡錠	effervescent tablet	\N	製	045993	\N	健喬	3	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
3	LICENSE:製:037598	LICENSE	Actein Granules 66.7mg	Actein	愛克痰	actein	愛克痰	EN:actein	66.7mg/g	66.7mg	Granules	顆粒劑	granules	\N	製	037598	SYNMOSA	健喬	4	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
4	LICENSE:製:004928	LICENSE	ACTIBEST S.C. Tab	ACTIBEST	沛多活杏必	actibest	沛多活杏必	EN:actibest	\N	\N	Sugar-coated Tablet	糖衣錠	tablet	\N	製	004928	\N	\N	5	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
5	LICENSE:製:031800	LICENSE	Algitab Chewable Tablets 200mg	Algitab	艾胃逆服	algitab	艾胃逆服	EN:algitab	0.2g/0.04g/0.03g	200mg/40mg/30mg	Chewable Tablet	咀嚼錠	tablet	\N	製	031800	\N	東洋	6	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
7	LICENSE:製:012407	LICENSE	ANTI-GI SUPPOSITORY	ANTI-GI	千痔康	anti-gi	千痔康	EN:anti-gi	\N	\N	Suppository	栓劑	suppository	\N	製	012407	\N	回春堂	8	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
8	LICENSE:製:043664	LICENSE	Asprin_100mg	ESPIN	安心平	espin	安心平	EN:espin	100mg	100mg	E.M. CAP.	腸溶微粒膠囊	capsule	\N	製	043664	EVEREST	\N	9	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
9	LICENSE:輸:022593	LICENSE	Atanaal_Capsule_5	Atanaal	壓達能	atanaal	壓達能	EN:atanaal	5mg	5mg	Soft Capsule	軟膠囊	capsule	\N	輸	022593	TOYO CAPSULE CO., LTD.	曼哈頓	10	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
11	LICENSE:製:057842	LICENSE	Azithromycin Zirocin 250mg	Zirocin	美妥欣	zirocin	美妥欣	EN:zirocin	250mg	250mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	057842	\N	南光	12	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
12	LICENSE:製:010282	LICENSE	Bacide Tabs	Bacide	菌特制	bacide	菌特制	EN:bacide	400mg/80mg	400mg/80mg	Tablet	錠劑	tablet	\N	製	010282	\N	榮民	13	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
111	BARCODE:104711144715304	BARCODE	Xarelto 15mg	Xarelto	拜瑞妥	xarelto	拜瑞妥	EN:xarelto	15mg	15mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	\N	\N	112	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
354	COMPOSITE_EN:5869548cc26983adb7fba2e0d7185d73eed1d159de73bf5caea773402f378b97	COMPOSITE_EN	ZANIDIP Lercanidipine HCI 10mg	ZANIDIP	\N	zanidip	\N	EN:zanidip	10mg	10mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	\N	\N	\N	\N	117	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
356	COMPOSITE_EN:c282c0a2b7baa1e5dbbc7a66956f1c76bc4750e557f4a26d0b045f15c0645aaf	COMPOSITE_EN	Zoloft	Zoloft	樂復得	zoloft	樂復得	EN:zoloft	50mg	50mg	Tablets	錠	tablet	\N	\N	\N	VIATRIS	\N	119	3	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08
257	COMPOSITE_EN:757ed412c0a5f3ac8ebe03bf03dfcd72eae494d983bbbed0957a14528738dfc6	COMPOSITE_EN	Cefadroxil 500mg	Cefadroxil	\N	cefadroxil	\N	EN:cefadroxil	500mg	500mg	\N	\N	\N	\N	\N	\N	\N	\N	20	3	2026-09-22 13:47:27.862953+08	2026-10-03 21:45:25.140722+08
112	BARCODE:5000456012010	BARCODE	xlgduo XR 10mg	Xlgduo XR	釋多糖	xlgduo xr	釋多糖	EN:xlgduo xr	10mg/1000mg	10mg/1000mg	Extended-release Film-coated Tablet	持續性藥效膜衣錠	film-coated tablet	extended-release	\N	\N	\N	\N	113	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
113	LICENSE:輸:023792	LICENSE	Xyzal 5mg	Xyzal	驅異樂	xyzal	驅異樂	EN:xyzal	5mg	5mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	輸	023792	GSK	\N	114	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
114	LICENSE:製:050145	LICENSE	Xyzine	Xyzine	萊欣	xyzine	萊欣	EN:xyzine	5mg	5mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	050145	\N	中國化學	115	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
115	LICENSE:製:061416	LICENSE	Youkoxia F.C. Tab. 60mg	Youkoxia	息樂炎	youkoxia	息樂炎	EN:youkoxia	60mg	60mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	061416	\N	永信	116	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
117	LICENSE:製:002963	LICENSE	ZM Calcium Gluconated Tablets	Calcium Gluconated	葡萄糖鈣丁片	calcium gluconated	葡萄糖鈣丁片	EN:calcium gluconated	\N	\N	Tablets	錠	tablet	\N	製	002963	ZM	昇銘	118	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
119	LICENSE:製:046013	LICENSE	Zolon F.C. Tab. 7.5mg	Zolon	樂比克	zolon	樂比克	EN:zolon	7.5mg	7.5mg	Film-coated Tablet	膜衣錠	film-coated tablet	\N	製	046013	\N	信東	120	3	2026-09-22 13:40:57.664939+08	2026-09-22 13:47:27.862953+08
\.


--
-- Data for Name: import_issues; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.import_issues (issue_id, import_run_id, source_row_number, folder_name, issue_code, issue_message, created_at) FROM stdin;
1	1	5	ACTIBEST S.C. Tab	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
2	1	5	ACTIBEST S.C. Tab	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
3	1	8	ANTI-GI SUPPOSITORY	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
4	1	20	Cefadroxil 500mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
5	1	33	Exelon	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
6	1	42	Glucophage	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
7	1	49	Jardiance Duo	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
8	1	50	KALIMATE	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
9	1	61	MgO 250mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
10	1	68	Nolvadex Tamoxifen 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
11	1	74	OxyContin	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
12	1	81	Rivotril	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
13	1	82	ROMICON-A	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
14	1	83	Rytmononm 150mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
15	1	84	Senokot	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
16	1	84	Senokot	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
17	1	85	Seroquel 25mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
18	1	86	Seroquel XR 50mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
19	1	89	Sketa Capsules	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
20	1	102	TIMING	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
21	1	112	Xarelto 15mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
22	1	113	xlgduo XR 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
23	1	117	ZANIDIP Lercanidipine HCI 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:40:57.664939+08
24	1	118	ZM Calcium Gluconated Tablets	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:40:57.664939+08
25	2	5	ACTIBEST S.C. Tab	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
26	2	5	ACTIBEST S.C. Tab	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
27	2	8	ANTI-GI SUPPOSITORY	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
28	2	20	Cefadroxil 500mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
29	2	33	Exelon	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
30	2	42	Glucophage	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
31	2	49	Jardiance Duo	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
32	2	50	KALIMATE	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
33	2	61	MgO 250mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
34	2	68	Nolvadex Tamoxifen 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
35	2	74	OxyContin	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
36	2	81	Rivotril	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
37	2	82	ROMICON-A	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
38	2	83	Rytmononm 150mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
39	2	84	Senokot	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
40	2	84	Senokot	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
41	2	85	Seroquel 25mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
42	2	86	Seroquel XR 50mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
43	2	89	Sketa Capsules	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
44	2	102	TIMING	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
45	2	112	Xarelto 15mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
46	2	113	xlgduo XR 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
47	2	117	ZANIDIP Lercanidipine HCI 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:41:57.826207+08
48	2	118	ZM Calcium Gluconated Tablets	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:41:57.826207+08
49	3	5	ACTIBEST S.C. Tab	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
50	3	5	ACTIBEST S.C. Tab	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
51	3	8	ANTI-GI SUPPOSITORY	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
52	3	20	Cefadroxil 500mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
53	3	33	Exelon	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
54	3	42	Glucophage	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
55	3	49	Jardiance Duo	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
56	3	50	KALIMATE	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
57	3	61	MgO 250mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
58	3	68	Nolvadex Tamoxifen 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
59	3	74	OxyContin	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
60	3	81	Rivotril	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
61	3	82	ROMICON-A	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
62	3	83	Rytmononm 150mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
63	3	84	Senokot	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
64	3	84	Senokot	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
65	3	85	Seroquel 25mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
66	3	86	Seroquel XR 50mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
67	3	89	Sketa Capsules	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
68	3	102	TIMING	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
69	3	112	Xarelto 15mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
70	3	113	xlgduo XR 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
71	3	117	ZANIDIP Lercanidipine HCI 10mg	MISSING_MANUFACTURER	允許欄位中缺少製造商	2026-09-22 13:47:27.862953+08
72	3	118	ZM Calcium Gluconated Tablets	MISSING_STRENGTH	允許欄位中缺少劑量	2026-09-22 13:47:27.862953+08
\.


--
-- Data for Name: import_runs; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.import_runs (import_run_id, source_file_name, source_file_sha256, started_at, finished_at, status, rows_read, rows_inserted, rows_updated, rows_skipped, rows_with_issues) FROM stdin;
1	藥品資料庫_補資料副本_20260919 - generated_drugs_review.csv	2c721aa46b53a0746b65dcb018b23abdb090ec142cc3dbf7ef1c65f75329ab91	2026-09-22 13:40:57.664939+08	2026-09-22 13:40:57.664939+08	COMPLETED	119	119	0	0	24
2	藥品資料庫_補資料副本_20260919 - generated_drugs_review.csv	2c721aa46b53a0746b65dcb018b23abdb090ec142cc3dbf7ef1c65f75329ab91	2026-09-22 13:41:57.826207+08	2026-09-22 13:41:57.826207+08	COMPLETED	119	119	0	0	24
3	藥品資料庫_補資料副本_20260919 - generated_drugs_review.csv	2c721aa46b53a0746b65dcb018b23abdb090ec142cc3dbf7ef1c65f75329ab91	2026-09-22 13:47:27.862953+08	2026-09-22 13:47:27.862953+08	COMPLETED	119	119	0	0	24
\.


--
-- Data for Name: ingredient_aliases; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.ingredient_aliases (alias_id, alias, normalized_alias, canonical, language_code, source) FROM stdin;
1	hydrochloride	hydrochloride	HCl	en	manual
2	hcl	hcl	HCl	en	manual
3	hci	hci	HCl	en	manual
4	hydrobromide	hydrobromide	HBr	en	manual
5	hbr	hbr	HBr	en	manual
\.


--
-- Data for Name: manufacturer_aliases; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.manufacturer_aliases (alias_id, alias, normalized_alias, canonical, alias_type, source) FROM stdin;
\.


--
-- Data for Name: matching_weights; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.matching_weights (field_name, weight) FROM stdin;
drug_name	35.00
ingredient	25.00
strength	20.00
manufacturer	12.00
dosage_form	8.00
\.


--
-- Data for Name: normalization_aliases; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.normalization_aliases (alias_id, field_name, alias, normalized_alias, canonical) FROM stdin;
\.


--
-- Name: dosage_form_aliases_alias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.dosage_form_aliases_alias_id_seq', 15, true);


--
-- Name: drug_aliases_alias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.drug_aliases_alias_id_seq', 1, false);


--
-- Name: drug_barcodes_barcode_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.drug_barcodes_barcode_id_seq', 78, true);


--
-- Name: drug_ingredients_drug_ingredient_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.drug_ingredients_drug_ingredient_id_seq', 302, true);


--
-- Name: drug_products_drug_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.drug_products_drug_id_seq', 357, true);


--
-- Name: import_issues_issue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.import_issues_issue_id_seq', 72, true);


--
-- Name: import_runs_import_run_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.import_runs_import_run_id_seq', 3, true);


--
-- Name: ingredient_aliases_alias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.ingredient_aliases_alias_id_seq', 5, true);


--
-- Name: manufacturer_aliases_alias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.manufacturer_aliases_alias_id_seq', 1, false);


--
-- Name: normalization_aliases_alias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.normalization_aliases_alias_id_seq', 1, false);


--
-- Name: dosage_form_aliases dosage_form_aliases_alias_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dosage_form_aliases
    ADD CONSTRAINT dosage_form_aliases_alias_key UNIQUE (alias);


--
-- Name: dosage_form_aliases dosage_form_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dosage_form_aliases
    ADD CONSTRAINT dosage_form_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: drug_aliases drug_aliases_drug_id_normalized_alias_language_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_aliases
    ADD CONSTRAINT drug_aliases_drug_id_normalized_alias_language_code_key UNIQUE (drug_id, normalized_alias, language_code);


--
-- Name: drug_aliases drug_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_aliases
    ADD CONSTRAINT drug_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: drug_barcodes drug_barcodes_barcode_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_barcodes
    ADD CONSTRAINT drug_barcodes_barcode_key UNIQUE (barcode);


--
-- Name: drug_barcodes drug_barcodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_barcodes
    ADD CONSTRAINT drug_barcodes_pkey PRIMARY KEY (barcode_id);


--
-- Name: drug_ingredients drug_ingredients_drug_id_ingredient_order_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_ingredients
    ADD CONSTRAINT drug_ingredients_drug_id_ingredient_order_key UNIQUE (drug_id, ingredient_order);


--
-- Name: drug_ingredients drug_ingredients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_ingredients
    ADD CONSTRAINT drug_ingredients_pkey PRIMARY KEY (drug_ingredient_id);


--
-- Name: drug_products drug_products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_products
    ADD CONSTRAINT drug_products_pkey PRIMARY KEY (drug_id);


--
-- Name: drug_products drug_products_source_record_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_products
    ADD CONSTRAINT drug_products_source_record_key_key UNIQUE (source_record_key);


--
-- Name: import_issues import_issues_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues
    ADD CONSTRAINT import_issues_pkey PRIMARY KEY (issue_id);


--
-- Name: import_runs import_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_runs
    ADD CONSTRAINT import_runs_pkey PRIMARY KEY (import_run_id);


--
-- Name: ingredient_aliases ingredient_aliases_alias_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_aliases
    ADD CONSTRAINT ingredient_aliases_alias_key UNIQUE (alias);


--
-- Name: ingredient_aliases ingredient_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ingredient_aliases
    ADD CONSTRAINT ingredient_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: manufacturer_aliases manufacturer_aliases_alias_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturer_aliases
    ADD CONSTRAINT manufacturer_aliases_alias_key UNIQUE (alias);


--
-- Name: manufacturer_aliases manufacturer_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.manufacturer_aliases
    ADD CONSTRAINT manufacturer_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: matching_weights matching_weights_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_weights
    ADD CONSTRAINT matching_weights_pkey PRIMARY KEY (field_name);


--
-- Name: normalization_aliases normalization_aliases_field_name_normalized_alias_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.normalization_aliases
    ADD CONSTRAINT normalization_aliases_field_name_normalized_alias_key UNIQUE (field_name, normalized_alias);


--
-- Name: normalization_aliases normalization_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.normalization_aliases
    ADD CONSTRAINT normalization_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: ix_drug_alias_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_drug_alias_trgm ON public.drug_aliases USING gin (normalized_alias public.gin_trgm_ops);


--
-- Name: ix_drug_barcode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_drug_barcode ON public.drug_products USING btree (source_record_key) WHERE (identity_key_type = 'BARCODE'::text);


--
-- Name: ix_drug_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_drug_family ON public.drug_products USING btree (product_family_key);


--
-- Name: ix_drug_name_en_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_drug_name_en_trgm ON public.drug_products USING gin (normalized_name_en public.gin_trgm_ops);


--
-- Name: ix_drug_name_zh; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_drug_name_zh ON public.drug_products USING btree (normalized_name_zh);


--
-- Name: ix_import_issues_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_issues_run ON public.import_issues USING btree (import_run_id, created_at DESC);


--
-- Name: uq_drug_license; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_drug_license ON public.drug_products USING btree (license_kind, license_number) WHERE (license_number IS NOT NULL);


--
-- Name: drug_aliases drug_aliases_drug_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_aliases
    ADD CONSTRAINT drug_aliases_drug_id_fkey FOREIGN KEY (drug_id) REFERENCES public.drug_products(drug_id) ON DELETE CASCADE;


--
-- Name: drug_barcodes drug_barcodes_drug_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_barcodes
    ADD CONSTRAINT drug_barcodes_drug_id_fkey FOREIGN KEY (drug_id) REFERENCES public.drug_products(drug_id) ON DELETE CASCADE;


--
-- Name: drug_ingredients drug_ingredients_drug_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_ingredients
    ADD CONSTRAINT drug_ingredients_drug_id_fkey FOREIGN KEY (drug_id) REFERENCES public.drug_products(drug_id) ON DELETE CASCADE;


--
-- Name: drug_products drug_products_import_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drug_products
    ADD CONSTRAINT drug_products_import_run_id_fkey FOREIGN KEY (import_run_id) REFERENCES public.import_runs(import_run_id);


--
-- Name: import_issues import_issues_import_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_issues
    ADD CONSTRAINT import_issues_import_run_id_fkey FOREIGN KEY (import_run_id) REFERENCES public.import_runs(import_run_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict FJP8xdyne2LtFqsUub3mBACBuxbUmvfq97pNSexP1QOqr19mAcpsBMpnBhNoMqU

