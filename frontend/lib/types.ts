export interface Span {
  start: number;
  end: number;
  text: string;
  label?: string;
}

export interface Trend { rising: boolean; escalate: boolean; reason?: string; trace?: number[] }
export interface Vital { [key: string]: number | null | undefined }
export interface Driver { label: string; value?: string | number; direction: string; contribution: number }

export interface Routing {
  pathway: string; specialty: string; specialist_available: boolean; notes: string[];
  beds_free: number; blocked: boolean;
  suggested_bed: string | null;
  suggested_clinician: string | null;
  suggested_clinician_name: string | null;
}

export interface Patient {
  id: string; display_id: string; age: number | null; complaint: string; transcript?: string;
  name?: string; sex?: string; registration_no?: string; lab_results?: any[];
  arrival_mode: string; status: string; assigned_esi?: string | null; esi: string;
  ari: number; waited: number; trace: number[]; trend: Trend; pending: boolean;
  confidence: string; pathway: string; routing: Routing;
  lab_evaluation?: { multiplier: number; reason: string | null } | null;
  medications?: Medication[];
  clinical_notes?: ClinicalNote[];
  sirs?: string[] | null;
  synergy_matched?: string[] | null;
  vitals: Vital; vitals_present: number; drivers: Driver[]; spans: Span[]; nlp_source?: string;
}

export interface Medication {
  id: number;
  medication_name: string;
  dosage: string;
  scheduled_time: string;
  status: "scheduled" | "given" | "held" | "cancelled";
  given_at?: string | null;
  notes?: string | null;
}

export interface ClinicalNote {
  id: number;
  note_type: "surgical" | "discharge_summary" | "follow_up";
  content: string;
  created_at: string;
}

// Bed/clinician status vocabulary — kept as string unions rather than a
// generic `string` so a typo in a status check fails at compile time, not
// silently at render time as an unstyled box.
export type BedStatus = "available" | "occupied" | "cleaning" | "unavailable";
export type ClinicianStatus = "available" | "busy" | "off_shift";

export interface Bed { id: string; ward: string; status: BedStatus; patient_id: string | null }
export interface Clinician {
  id: string; name: string; specialty: string; status: ClinicianStatus; patient_id: string | null;
}

export type AmbulanceStatus = "dispatched" | "en_route" | "arrived";

export interface AmbulancePosition {
  id: string; display_id: string; origin: string; note: string;
  status: AmbulanceStatus;
  distance_km: number; eta_min: number; bearing: number;
  total_distance_km: number; progress: number;
  vehicle_number: string; driver: string; paramedic: string;
  vehicle_type: string; callsign: string;
}

export interface BoardState {
  rows: Patient[];
  capacity: { beds: Record<string, number>; specialists: Record<string, number>; staff_on: number };
  beds: Bed[];
  clinicians: Clinician[];
  ambulances: AmbulancePosition[];
  agreement: { rate: number | null; total: number; accepted: number };
  events: { at: string; kind: string; text: string }[];
  model: { roc_auc: number; sensitivity: number; undertriage_rate: number; n_test: number };
}

export interface TestResult {
  test_name: string;
  value: string;
  unit?: string | null;
  reference_range?: string | null;
  abnormality_flag?: "H" | "L" | "A" | null;
}

export interface LabReport {
  name?: string | null;
  age_years?: number | null;
  sex?: string | null;
  referred_by?: string | null;
  registration_no?: string | null;
  report_date?: string | null;
  test_results: TestResult[];
  // Inferred server-side from test_results (see backend/lab/pipeline.py) —
  // present only for the physical-exam values a report happened to carry.
  vitals?: Partial<Record<"heart_rate" | "systolic_bp" | "diastolic_bp" | "resp_rate" | "spo2" | "temperature", number>>;
}

export interface IntakePayload {
  personal_details: {
    name: string;
    age_years: number | null;
    sex: string;
    referred_by: string;
    registration_no: string;
    report_date: string;
  };
  presentation: {
    complaint: string;
    nursing_assessment: string;
  };
  vitals: Record<string, number | null>;
  laboratory: {
    test_results: TestResult[];
  };
}
