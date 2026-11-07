import React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FiCompass } from "react-icons/fi";

// An address inside the app that matches no page. It used to render an
// empty area under the top bar, with nothing saying why.
const PageNotFound = () => {
  const { t } = useTranslation();
  return (
    <div className="ds-section">
      <div className="ds-empty-state" role="status">
        <div className="ds-empty-state-icon"><FiCompass /></div>
        <h1 className="ds-empty-state-title">{t("notFound.title", "Page not found")}</h1>
        <div className="ds-empty-state-body">{t("notFound.body", "This address matches no SerOps page.")}</div>
        <Link className="ds-btn ds-btn-primary mt-3" to="/dash">{t("notFound.back", "Back to Overview")}</Link>
      </div>
    </div>
  );
};

export default PageNotFound;
