import NavigationSidebar from "./NavigationSidebar";

export default function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="app-shell"><NavigationSidebar /><div className="app-content">{children}</div></div>;
}
