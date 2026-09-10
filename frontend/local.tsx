import React from 'react';
import { createRoot } from 'react-dom/client';
import FlyApp from './components/fly-app';
import './app/globals.css';
import './app/flykeeper.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><FlyApp /></React.StrictMode>);
