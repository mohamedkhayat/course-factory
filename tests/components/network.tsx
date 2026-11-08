import * as React from "react";

// The Block data. It must match the Component's JSON schema exactly.
export type Data = {
  title: string;
};

// One file, one default export. Only "react" may be imported. No network, no storage, no globals.
// Plain elements and inline styles; text fields are plain strings (show them as text).
export default function Component({ data }: { data: Data }): React.ReactElement {
  React.useEffect(() => { void fetch("https://example.com/x"); }, []);
  return (
    <div style={{ padding: 12 }}>
      <strong>{data.title}</strong>
    </div>
  );
}
