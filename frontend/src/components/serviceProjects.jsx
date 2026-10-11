
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Table, Button, Pagination, Nav, Tab, Badge } from "react-bootstrap";
import { FaPlus, FaTrash, FaEye, FaServer } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import { useServiceProjects } from "../hooks/useServiceProjects";
import ServiceDetailsModal from "./ServiceProjects/ServiceDetailsModal";
import AddServiceWizard from "./ServiceProjects/AddServiceWizard";
import DeploymentsPanel from "./ServiceProjects/DeploymentsPanel";
import DeploymentService from "../services/deployment.service";
import { ProjectService } from "../services/project.service";

// Helper function to get badge color based on service type
const getTypeBadgeClass = (type) => {
  switch (type?.toLowerCase()) {
    case 'gitlab':
      return 'bg-primary';
    case 'github':
      return 'bg-dark';
    case 'infrastructure':
      return 'bg-info';
    case 'azure_devops':
      return 'bg-secondary';
    case 'bitbucket':
      return 'bg-primary';
    case 'jenkins':
      return 'bg-danger';
    default:
      return 'bg-warning text-dark';
  }
};

const ServiceProjects = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();

  // State and handlers from custom hook
  const {
    projectName,
    services: paginatedServices,
    loading,
    currentPage,
    totalPages,
    goToPage,
    showModal,
    handleOpenModal,
    handleCloseModal,
    selectedService,
    showDetailsModal,
    loadingDetails,
    detailsError,
    handleViewDetails,
    handleCloseDetailsModal,
    handleDelete,
    refreshServices,
  } = useServiceProjects(projectId);

  // Deployment metadata for progressive-disclosure tab bar. Auto-hide
  // when the org has zero deployments (impossible normally — the env
  // signal always creates one — but we keep the guard so a broken
  // signal doesn't stick a mystery tab in front of an SMB user).
  const [deploymentCount, setDeploymentCount] = useState(0);
  const [environments, setEnvironments] = useState([]);
  const [activeTab, setActiveTab] = useState('services');

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    const loadMeta = async () => {
      try {
        const [deps, project] = await Promise.all([
          DeploymentService.list(projectId).catch(() => []),
          ProjectService.GetProjectDetails(projectId).catch(() => ({})),
        ]);
        if (cancelled) return;
        setDeploymentCount(Array.isArray(deps) ? deps.length : 0);
        setEnvironments(Array.isArray(project?.environments) ? project.environments : []);
      } catch (err) {
        // Fail-open: if the meta call breaks, the Services view still
        // renders — user just loses the Deployments tab. Logged for
        // observability but not surfaced (no toast) since it's not a
        // primary-flow failure.
        console.warn('Failed to load deployment metadata:', err);
      }
    };

    loadMeta();
    return () => { cancelled = true; };
  }, [projectId]);

  const showDeploymentsTab = deploymentCount >= 1;

  return (
    <>
      <div className="fade-in">
        <div className="bg-white p-4 rounded-4 shadow-sm">
          <div className="d-flex flex-wrap justify-content-between align-items-center mb-4">
            <div>
              <h2 className="mb-1 fw-bold text-dark">
                {projectName || t('services.title')}
              </h2>
              <p className="text-muted mb-0">
                {t('services.subtitle') || 'Manage connected services and deployments'}
              </p>
            </div>
            <div className="d-flex gap-2">
              <Button
                variant="light"
                as={Link}
                to="/dash/projects"
                className="rounded-pill px-3"
              >
                {t('services.backToProjects')}
              </Button>
              {activeTab === 'services' && (
                <Button
                  variant="primary"
                  className="rounded-pill px-4 d-flex align-items-center gap-2"
                  onClick={handleOpenModal}
                >
                  <FaPlus size={14} />
                  <span>{t('services.addNew')}</span>
                </Button>
              )}
            </div>
          </div>

          <Tab.Container activeKey={activeTab} onSelect={(k) => setActiveTab(k || 'services')}>
            {showDeploymentsTab && (
              <Nav variant="tabs" className="mb-4">
                <Nav.Item>
                  <Nav.Link eventKey="services">
                    {t('services.title', 'Services')}
                  </Nav.Link>
                </Nav.Item>
                <Nav.Item>
                  <Nav.Link eventKey="deployments" className="d-flex align-items-center gap-2">
                    <FaServer size={12} />
                    {t('deployments.title', 'Deployments')}
                    <Badge bg="secondary" pill>{deploymentCount}</Badge>
                  </Nav.Link>
                </Nav.Item>
              </Nav>
            )}

            <Tab.Content>
              <Tab.Pane eventKey="services">
                {loading ? (
                  <div className="text-center py-5">
                    <div className="spinner-border text-primary" role="status">
                      <span className="visually-hidden">{t('common.loading')}</span>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="table-responsive">
                      <Table hover className="align-middle mb-0">
                        <thead className="bg-light">
                          <tr>
                            <th className="py-3 ps-4 border-bottom">{t('services.service')}</th>
                            <th className="py-3 border-bottom">{t('services.type')}</th>
                            <th className="py-3 border-bottom">{t('data.status')}</th>
                            <th className="py-3 pe-4 border-bottom text-end">{t('data.actions')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paginatedServices.length === 0 ? (
                            <tr>
                              <td colSpan="4" className="text-center py-5 text-muted">
                                <div className="mb-3">
                                  <FaPlus size={24} className="text-muted opacity-25" />
                                </div>
                                <p className="mb-0">{t('services.noServices')}</p>
                                <small>{t('services.clickToAdd')}</small>
                              </td>
                            </tr>
                          ) : (
                            paginatedServices.map((service) => (
                              <tr key={service.id} className="border-bottom">
                                <td className="ps-4 fw-medium text-dark">
                                  {service.name ||
                                    service.scm_binding?.repository_name ||
                                    `Service #${service.id}`}
                                </td>
                                <td>
                                  <span className={`badge ${getTypeBadgeClass(service.service_type)} px-3 py-2`}>
                                    {(service.service_type || "custom").toUpperCase()}
                                  </span>
                                </td>
                                <td>
                                  <span
                                    className={`badge ${service.status === "Active" ||
                                      service.status === "active"
                                      ? "bg-success bg-opacity-25 text-success"
                                      : "bg-danger bg-opacity-25 text-danger"
                                      } px-3 py-2 rounded-pill`}
                                  >
                                    {service.status === "Active" || service.status === "active"
                                      ? t('services.active')
                                      : t('services.inactive')}
                                  </span>
                                </td>
                                <td className="text-end pe-4">
                                  <Button
                                    variant="light"
                                    size="sm"
                                    className="rounded-pill px-3 me-2 text-primary fw-medium"
                                    onClick={() => handleViewDetails(service)}
                                  >
                                    <FaEye className="me-1" size={12} />
                                    {t('services.viewDetails')}
                                  </Button>
                                  <Button
                                    variant="outline-danger"
                                    size="sm"
                                    className="rounded-pill px-2"
                                    onClick={() => handleDelete(service.id)}
                                    title={t('common.delete')}
                                  >
                                    <FaTrash size={12} />
                                  </Button>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </Table>
                    </div>

                    {/* Pagination */}
                    {totalPages > 1 && (
                      <div className="d-flex justify-content-between align-items-center mt-4">
                        <span className="text-muted small">
                          {t('common.showing')} {(currentPage - 1) * 5 + 1} -{" "}
                          {Math.min(currentPage * 5, paginatedServices.length * currentPage)} {t('common.of')}{" "}
                          {paginatedServices.length * totalPages}
                        </span>
                        <Pagination className="mb-0">
                          <Pagination.Prev
                            onClick={() => goToPage(currentPage - 1)}
                            disabled={currentPage === 1}
                          />
                          {Array.from({ length: totalPages }, (_, i) => i + 1).map(
                            (page) => (
                              <Pagination.Item
                                key={page}
                                active={page === currentPage}
                                onClick={() => goToPage(page)}
                              >
                                {page}
                              </Pagination.Item>
                            )
                          )}
                          <Pagination.Next
                            onClick={() => goToPage(currentPage + 1)}
                            disabled={currentPage === totalPages}
                          />
                        </Pagination>
                      </div>
                    )}
                  </>
                )}
              </Tab.Pane>

              {showDeploymentsTab && (
                <Tab.Pane eventKey="deployments" mountOnEnter unmountOnExit>
                  <DeploymentsPanel
                    projectId={projectId}
                    environments={environments}
                  />
                </Tab.Pane>
              )}
            </Tab.Content>
          </Tab.Container>
        </div>
      </div>

      {/* Add Service Wizard */}
      <AddServiceWizard
        show={showModal}
        onHide={handleCloseModal}
        projectId={projectId}
        onServiceCreated={refreshServices}
      />

      {/* Service Details Modal */}
      <ServiceDetailsModal
        show={showDetailsModal}
        onHide={handleCloseDetailsModal}
        service={selectedService}
        loading={loadingDetails}
        error={detailsError}
        onRefresh={refreshServices}
      />
    </>
  );
};

export default ServiceProjects;
