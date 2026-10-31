import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router";
import "@fontsource-variable/figtree";
import "./styles.css";
import { App } from "./App";
import { installInputModality } from "./components/inputModality";
const stopModality = installInputModality();
import.meta.hot?.dispose(stopModality);
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
