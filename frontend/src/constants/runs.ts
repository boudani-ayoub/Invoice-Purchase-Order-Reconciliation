export const RUNS_API_PATH = "/api/v1/runs";
export const HISTORY_PATH = "/history";
export const runPath = (id: string) =>
  `${HISTORY_PATH}/${encodeURIComponent(id)}`;
export const runApiPath = (id: string) =>
  `${RUNS_API_PATH}/${encodeURIComponent(id)}`;
export const createRunPath = (mode: string) => `${RUNS_API_PATH}/${mode}`;
export const RUN_TITLE_LIMIT = 120;
export const RUN_NOTE_LIMIT = 4000;
export const HISTORY_PAGE_SIZE = 25;
export const RETENTION_COPY =
  "Raw uploaded files are not retained. Validated records and analysis results are saved to your organization's history.";
export const RUN_CONFLICT_MESSAGE =
  "This run was updated by someone else. Refresh to see the latest version.";
