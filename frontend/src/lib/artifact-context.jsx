import { createContext, useContext } from "react";

export const ArtifactContext = createContext(null);
export const useArtifactPreview = () => useContext(ArtifactContext);
