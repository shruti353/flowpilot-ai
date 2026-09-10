import { useState } from "react";
import type { FormEvent } from "react";
import type { ActionFieldValues, MissingFieldSpec, StoredPlan } from "../types/plan";
import { OPERATION_LABELS } from "../utils/labels";

interface MissingFieldsFormProps {
  plan: StoredPlan;
  onSubmit: (actions: ActionFieldValues[]) => void;
  isSubmitting: boolean;
}

// Keyed by field name for text/date/time/number/select; a "datetime" field
// is split into `${field}__date` and `${field}__time` since the requirement
// is a separate date + time picker, combined into one value on submit.
type FieldValues = Record<string, string>;

function isFieldFilled(field: MissingFieldSpec, value: FieldValues): boolean {
  if (field.type === "datetime") {
    return Boolean(value[`${field.field}__date`]) && Boolean(value[`${field.field}__time`]);
  }
  return Boolean(value[field.field]);
}

function toSubmittedValue(field: MissingFieldSpec, value: FieldValues): unknown {
  if (field.type === "datetime") {
    return `${value[`${field.field}__date`]}T${value[`${field.field}__time`]}`;
  }
  if (field.type === "number") {
    return Number(value[field.field]);
  }
  return value[field.field];
}

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: MissingFieldSpec;
  value: FieldValues;
  onChange: (patch: FieldValues) => void;
}) {
  if (field.type === "datetime") {
    return (
      <span className="missing-fields-form__datetime">
        <input
          type="date"
          aria-label={`${field.label} date`}
          value={value[`${field.field}__date`] ?? ""}
          onChange={(event) => onChange({ [`${field.field}__date`]: event.target.value })}
        />
        <input
          type="time"
          lang="en-US"
          aria-label={`${field.label} time`}
          value={value[`${field.field}__time`] ?? ""}
          onChange={(event) => onChange({ [`${field.field}__time`]: event.target.value })}
        />
      </span>
    );
  }

  if (field.type === "select") {
    return (
      <select
        value={value[field.field] ?? ""}
        onChange={(event) => onChange({ [field.field]: event.target.value })}
      >
        <option value="" disabled>
          Select...
        </option>
        {(field.options ?? []).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }

  const inputType = field.type === "number" || field.type === "date" || field.type === "time" ? field.type : "text";
  return (
    <input
      type={inputType}
      // Nudges the native time picker toward a 12-hour AM/PM display
      // (e.g. Chromium/WebKit honor this regardless of OS locale) - the
      // submitted value is always 24-hour "HH:mm" either way, per the
      // HTML spec, so this only affects presentation.
      lang={inputType === "time" ? "en-US" : undefined}
      value={value[field.field] ?? ""}
      onChange={(event) => onChange({ [field.field]: event.target.value })}
    />
  );
}

export function MissingFieldsForm({ plan, onSubmit, isSubmitting }: MissingFieldsFormProps) {
  const [valuesByAction, setValuesByAction] = useState<Record<string, FieldValues>>({});

  const actionsWithMissingFields = (plan.execution_plan?.actions ?? []).filter(
    (action) => action.missing_fields.length > 0,
  );

  if (actionsWithMissingFields.length === 0) {
    return null;
  }

  const allFilled = actionsWithMissingFields.every((action) =>
    action.missing_fields.every((field) => isFieldFilled(field, valuesByAction[action.action_id] ?? {})),
  );

  const handleFieldChange = (actionId: string, patch: FieldValues) => {
    setValuesByAction((prev) => ({
      ...prev,
      [actionId]: { ...(prev[actionId] ?? {}), ...patch },
    }));
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const actions: ActionFieldValues[] = actionsWithMissingFields.map((action) => {
      const values = valuesByAction[action.action_id] ?? {};
      const submitted: Record<string, unknown> = {};
      for (const field of action.missing_fields) {
        submitted[field.field] = toSubmittedValue(field, values);
      }
      return { action_id: action.action_id, values: submitted };
    });
    onSubmit(actions);
  };

  return (
    <form className="missing-fields-form" onSubmit={handleSubmit}>
      <p className="missing-fields-form__intro">
        This plan is missing some required information. Fill it in to continue.
      </p>
      {actionsWithMissingFields.map((action) => (
        <fieldset className="missing-fields-form__action" key={action.action_id}>
          <legend>{OPERATION_LABELS[action.operation]}</legend>
          {action.missing_fields.map((field) => (
            <label className="missing-fields-form__field" key={field.field}>
              <span>{field.label}</span>
              <FieldControl
                field={field}
                value={valuesByAction[action.action_id] ?? {}}
                onChange={(patch) => handleFieldChange(action.action_id, patch)}
              />
            </label>
          ))}
        </fieldset>
      ))}
      <button type="submit" className="btn btn--primary" disabled={!allFilled || isSubmitting}>
        {isSubmitting ? "Updating..." : "Update Plan"}
      </button>
    </form>
  );
}
