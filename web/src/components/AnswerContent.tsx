import { stripAnswerCitations } from "../lib/formatAnswer";

type Props = {
  content: string;
};

function formatInline(text: string, keyPrefix: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={`${keyPrefix}-b-${i}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${keyPrefix}-t-${i}`}>{part}</span>;
  });
}

export function AnswerContent({ content }: Props) {
  const body = stripAnswerCitations(content);
  const blocks = body.split(/\n{2,}/);

  return (
    <div className="answer-content">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const isList = lines.every((line) => line.trim() === "" || /^\d+\.\s/.test(line.trim()));

        if (isList && lines.some((line) => /^\d+\.\s/.test(line.trim()))) {
          return (
            <ol key={`list-${i}`} className="answer-list">
              {lines
                .filter((line) => line.trim())
                .map((line, j) => {
                  const item = line.replace(/^\d+\.\s*/, "");
                  return <li key={`item-${i}-${j}`}>{formatInline(item, `li-${i}-${j}`)}</li>;
                })}
            </ol>
          );
        }

        return (
          <p key={`p-${i}`} className="answer-paragraph">
            {lines.map((line, j) => (
              <span key={`line-${i}-${j}`}>
                {j > 0 && <br />}
                {formatInline(line, `p-${i}-${j}`)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}
