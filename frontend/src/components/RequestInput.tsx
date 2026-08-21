import { useState, type FormEvent } from "react";

interface RequestInputProps {
  onSubmit: (text: string) => void;
  isLoading: boolean;
}

export function RequestInput({ onSubmit, isLoading }: RequestInputProps) {
  const [text, setText] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
  };

  return (
    <form className="request-input" onSubmit={handleSubmit}>
      <textarea
        className="request-input__textarea"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Enter your request here... e.g. Schedule a meeting with my AI team tomorrow at 3 PM and create a task to prepare the demo."
        rows={3}
        disabled={isLoading}
      />
      <button type="submit" className="btn btn--primary" disabled={isLoading || !text.trim()}>
        {isLoading ? "Generating..." : "Generate Plan"}
      </button>
    </form>
  );
}
