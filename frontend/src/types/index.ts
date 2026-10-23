export interface Organization {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_at: string;
}

export interface OrganizationMember {
  id: string;
  user_id: string;
  email: string;
  role: 'owner' | 'admin' | 'member';
  created_at?: string | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  org_id: string;
  app_url?: string;
  created_at: string;
}

export interface TestStep {
  id: string;
  step_number: number;
  action: 'navigate' | 'fill' | 'click' | 'verify_url' | 'verify_text' | 'discover_page' | 'clear' | 'check' | 'uncheck' | 'verify_not_text' | 'verify_not_url' | 'select_option';
  target: string;
  value?: string;
  expected_result?: string;
}

export interface TestCase {
  id: string;
  name: string;
  description?: string;
  project_id: string;
  csv_filename?: string;
  is_active: boolean;
  steps: TestStep[];
  created_at: string;
}

export interface StepDetail {
  step_number: number;
  action: string;
  target?: string | null;
  value?: string | null;
  expected_result?: string | null;
  original_instruction?: string | null;
  status: 'passed' | 'failed' | 'skipped' | 'running' | 'error';
  duration_ms?: number | null;
  category?: string | null;
  failure_reason?: string | null;
  verification_result?: {
    type?: string;
    expected?: string;
    actual?: string;
    matched?: boolean;
    preview?: string;
  } | null;
}

export interface StepSummary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
}

export interface TestRun {
  id: string;
  project_id: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'error';
  started_at?: string;
  completed_at?: string;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  total_steps?: number;
  passed_steps?: number;
  failed_steps?: number;
  skipped_steps?: number;
  error_message?: string;
  video_path?: string;
  created_at: string;
}

export interface TestResult {
  id: string;
  run_id: string;
  test_case_id: string;
  status: 'passed' | 'failed' | 'error' | 'skipped';
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  screenshot_path?: string;
  video_path?: string;
  log_output?: string;
  steps?: StepDetail[];
  step_summary?: StepSummary;
  test_case?: TestCase;
}

export interface Artifact {
  id: string;
  run_id: string;
  result_id?: string;
  artifact_type: 'screenshot' | 'video' | 'log';
  file_path: string;
  file_size?: number;
  mime_type?: string;
  created_at: string;
}

export interface ValidationError {
  row: number;
  column: string;
  message: string;
}

export interface ValidationResult {
  is_valid: boolean;
  errors: ValidationError[];
  warnings: ValidationError[];
  row_count: number;
  test_case_count: number;
  parsed_cases?: TestCase[];
}

export interface ParsedStepItem {
  line_number: number;
  raw_instruction: string;
  is_valid: boolean;
  action?: string | null;
  target?: string | null;
  value?: string | null;
  expected_result?: string | null;
  confidence?: number;
  error?: string | null;
}

export interface ParseInstructionsError {
  line: number;
  instruction: string;
  message: string;
}

export interface ParseInstructionsResponse {
  is_valid: boolean;
  total_lines: number;
  valid_steps_count: number;
  steps: ParsedStepItem[];
  errors: ParseInstructionsError[];
}

export interface DashboardStats {
  total_organizations: number;
  total_projects: number;
  total_test_cases: number;
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  recent_runs: TestRun[];
}

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

export interface Membership {
  id: string;
  org_id: string;
  org_name: string;
  org_slug: string;
  role: string;
}

export interface UserProfile {
  user: User;
  memberships: Membership[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string | null;
  organization_name?: string | null;
}

export interface ForgotPasswordPayload {
  email: string;
}

export interface ResetPasswordPayload {
  token: string;
  new_password: string;
}

export interface GenericMessageResponse {
  message: string;
}

export interface TokenVerificationResponse {
  valid: boolean;
  message?: string | null;
}

export interface AuthContextType {
  user: User | null;
  profile: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (credentials: LoginCredentials) => Promise<void>;
  register: (data: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}


export interface ProjectVariable {
  id: string;
  project_id: string;
  name: string;
  value?: string | null;
  is_secret: boolean;
  description?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectVariableCreate {
  name: string;
  value?: string | null;
  is_secret?: boolean;
  description?: string | null;
}

export interface ProjectVariableUpdate {
  name?: string | null;
  value?: string | null;
  is_secret?: boolean | null;
  description?: string | null;
}
