import type { Metadata } from 'next';
import './globals.css';
import './flykeeper.css';
export const metadata: Metadata = {title: 'Flykeeper — Drosophila breeding manager', description: 'Your local culture calendar and breeding workspace.'};
export default function RootLayout({children}: {children: React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
