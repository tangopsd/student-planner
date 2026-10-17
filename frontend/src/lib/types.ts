export type Day = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export type ItemType = "assignment" | "quiz" | "exam" | "event" | "personal";

export type ItemSource = "canvas" | "voice" | "manual";

export type ItemStatus = "open" | "done";

export type Item = {
  id: string;
  title: string;
  course: string | null;
  type: ItemType;
  due_or_start: string;
  source: ItemSource;
  estimated_effort_hours: number | null;
  locked: boolean;
  status: ItemStatus;
  description: string;
};

export type Week = {
  week_start: string;
  week_end: string;
  label: string;
  relation: "past" | "current" | "upcoming";
  items: Item[];
};

export type StudyWindow = {
  day: Day;
  start: string;
  end: string;
};

export type Commitment = {
  id?: string;
  title: string;
  course: string | null;
  day: Day;
  start: string;
  end: string;
};

export type Profile = {
  waking_hours: { wake: string; sleep: string };
  fixed_commitments: Commitment[];
  preferred_study_windows: StudyWindow[];
  daily_capacity_hours: number;
};

export type ImportResult = {
  created: number;
  updated: number;
  parsed: number;
  items: Item[];
};

export type Classification = {
  type: ItemType;
  locked: boolean;
  matched: boolean;
};
