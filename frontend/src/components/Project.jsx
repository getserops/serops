import React, { useState, useEffect } from "react";
import {
  Table,
  Pagination,
  Button,
  Container,
  Modal,
  Form,
  Alert,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { FaPlus, FaEdit, FaTrash } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import { ProjectService } from "../services/project.service";

const Project = () => {
  const { t } = useTranslation();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [showModal, setShowModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deletingProject, setDeletingProject] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [formData, setFormData] = useState({
    name: "",
    description: "",
  });

  // Environment configuration state
  const [environments, setEnvironments] = useState([
    { name: 'development', display_name: 'Development', branch_patterns: ['develop', 'dev', 'feature/*'], is_active: true },
    { name: 'staging', display_name: 'Staging', branch_patterns: ['staging', 'release/*'], is_active: false },
    { name: 'production', display_name: 'Production', branch_patterns: ['main', 'master'], is_active: true },
  ]);

  const pageSize = 5;
  const totalPages = Math.ceil(projects.length / pageSize);

  const paginatedProjects = projects.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  const goToPage = (pageNumber) => {
    if (pageNumber < 1 || pageNumber > totalPages) return;
    setCurrentPage(pageNumber);
  };

  const handleOpenModal = () => {
    setShowModal(true);
    setSubmitError(null);
    setSubmitSuccess(false);
    setFormData({
      name: "",
      description: "",
    });
    // Reset environments to defaults
    setEnvironments([
      { name: 'development', display_name: 'Development', branch_patterns: ['develop', 'dev', 'feature/*'], is_active: true },
      { name: 'staging', display_name: 'Staging', branch_patterns: ['staging', 'release/*'], is_active: false },
      { name: 'production', display_name: 'Production', branch_patterns: ['main', 'master'], is_active: true },
    ]);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setSubmitError(null);
    setSubmitSuccess(false);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setSubmitError(null);
  };

  // Toggle environment active state
  const handleEnvironmentToggle = (envName) => {
    setEnvironments(prev =>
      prev.map(env =>
        env.name === envName
          ? { ...env, is_active: !env.is_active }
          : env
      )
    );
  };

  // Update branch patterns for an environment
  const handlePatternChange = (envName, patternsString) => {
    const patterns = patternsString.split(',').map(p => p.trim()).filter(p => p);
    setEnvironments(prev =>
      prev.map(env =>
        env.name === envName
          ? { ...env, branch_patterns: patterns }
          : env
      )
    );
  };

  // Add custom environment
  const handleAddCustomEnvironment = () => {
    const newEnvName = prompt(t('projects.customEnvName') || 'Enter environment name (e.g., qa, uat):');
    if (!newEnvName) return;

    const sanitizedName = newEnvName.toLowerCase().replace(/[^a-z0-9]/g, '-');

    // Check for duplicates
    if (environments.find(e => e.name === sanitizedName)) {
      alert(t('projects.envExists') || 'Environment already exists');
      return;
    }

    setEnvironments(prev => [
      ...prev,
      {
        name: sanitizedName,
        display_name: newEnvName.charAt(0).toUpperCase() + newEnvName.slice(1),
        branch_patterns: [sanitizedName, `${sanitizedName}/*`],
        is_active: true,
      }
    ]);
  };

  // Remove custom environment
  const handleRemoveEnvironment = (envName) => {
    // Don't allow removing default environments
    const defaultEnvs = ['development', 'staging', 'production'];
    if (defaultEnvs.includes(envName)) return;

    setEnvironments(prev => prev.filter(env => env.name !== envName));
  };

  const handleSubmit = async () => {
    if (!formData.name) {
      setSubmitError(t('projects.nameRequired'));
      return;
    }

    // Check at least one environment is selected
    const activeEnvs = environments.filter(e => e.is_active);
    if (activeEnvs.length === 0) {
      setSubmitError(t('projects.envRequired') || 'Please select at least one environment');
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(false);

    try {
      await ProjectService.CreateProject({
        name: formData.name,
        description: formData.description || "",
        environments: activeEnvs,  // Send only active environments
      });

      setSubmitSuccess(true);
      setTimeout(() => {
        handleCloseModal();
        fetchProjects();
      }, 1500);
    } catch (error) {
      let errorMessage = t('projects.createError');
      if (error.response) {
        errorMessage = error.response.data?.error || errorMessage;
      }
      setSubmitError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const data = await ProjectService.GetProjects();
      setProjects(data);
    } catch (error) {
      console.error("Failed to fetch projects:", error);
    } finally {
      setLoading(false);
    }
  };

  // Handle edit project
  const handleEditProject = async (project) => {
    setEditingProject(project);
    setFormData({
      name: project.name,
      description: project.description || "",
    });

    // Fetch project environments
    try {
      const details = await ProjectService.GetProjectDetails(project.id);
      if (details.environments && details.environments.length > 0) {
        setEnvironments(details.environments.map(env => ({
          name: env.name,
          display_name: env.display_name || env.name.charAt(0).toUpperCase() + env.name.slice(1),
          branch_patterns: env.branch_patterns || [],
          is_active: env.is_active,
        })));
      } else {
        // Default environments if none exist
        setEnvironments([
          { name: 'development', display_name: 'Development', branch_patterns: ['develop', 'dev', 'feature/*'], is_active: true },
          { name: 'staging', display_name: 'Staging', branch_patterns: ['staging', 'release/*'], is_active: false },
          { name: 'production', display_name: 'Production', branch_patterns: ['main', 'master'], is_active: true },
        ]);
      }
    } catch (error) {
      console.error("Failed to fetch project details:", error);
    }

    setShowModal(true);
    setSubmitError(null);
    setSubmitSuccess(false);
  };

  // Handle delete project confirmation
  const handleDeleteProject = (project) => {
    setDeletingProject(project);
    setShowDeleteModal(true);
  };

  // Confirm delete project
  const handleConfirmDelete = async () => {
    if (!deletingProject) return;

    setIsDeleting(true);
    try {
      await ProjectService.DeleteProject(deletingProject.id);
      setShowDeleteModal(false);
      setDeletingProject(null);
      fetchProjects();
    } catch (error) {
      console.error("Failed to delete project:", error);
      alert(t('projects.deleteError') || 'Failed to delete project');
    } finally {
      setIsDeleting(false);
    }
  };

  // Handle submit (create or update)
  const handleFormSubmit = async () => {
    if (!formData.name) {
      setSubmitError(t('projects.nameRequired'));
      return;
    }

    const activeEnvs = environments.filter(e => e.is_active);
    if (activeEnvs.length === 0) {
      setSubmitError(t('projects.envRequired') || 'Please select at least one environment');
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      if (editingProject) {
        // Update existing project
        await ProjectService.UpdateProject(editingProject.id, {
          name: formData.name,
          description: formData.description || "",
          environments: activeEnvs,
        });
      } else {
        // Create new project
        await ProjectService.CreateProject({
          name: formData.name,
          description: formData.description || "",
          environments: activeEnvs,
        });
      }

      setSubmitSuccess(true);
      setTimeout(() => {
        handleCloseModal();
        setEditingProject(null);
        fetchProjects();
      }, 1500);
    } catch (error) {
      let errorMessage = editingProject ? t('projects.updateError') : t('projects.createError');
      if (error.response) {
        errorMessage = error.response.data?.error || errorMessage;
      }
      setSubmitError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fade-in">
      <div className="bg-white p-4 rounded-4 shadow-sm">
        <div className="d-flex flex-wrap justify-content-between align-items-center mb-4">
          <div>
            <h2 className="mb-1 fw-bold text-dark">{t('projects.title')}</h2>
            <p className="text-muted mb-0">{t('projects.subtitle')}</p>
          </div>
          <Button
            variant="primary"
            className="rounded-pill px-4 d-flex align-items-center gap-2"
            onClick={handleOpenModal}
          >
            <FaPlus size={14} />
            <span>{t('projects.newProject')}</span>
          </Button>
        </div>

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
                    <th className="py-3 ps-4 border-bottom rounded-start">{t('projects.name')}</th>
                    <th className="py-3 border-bottom">{t('projects.description')}</th>
                    <th className="py-3 border-bottom">{t('projects.createdDate')}</th>
                    <th className="py-3 pe-4 border-bottom rounded-end text-end">{t('data.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedProjects.length > 0 ? (
                    paginatedProjects.map((project) => (
                      <tr key={project.id} className="border-bottom">
                        <td className="ps-4 fw-medium text-dark">{project.name}</td>
                        <td className="text-muted">
                          {project.description || "-"}
                        </td>
                        <td className="text-muted">
                          {new Date(project.created_at).toLocaleDateString()}
                        </td>
                        <td className="text-end pe-4">
                          <Button
                            variant="light"
                            size="sm"
                            className="rounded-pill px-3 me-2 text-primary fw-medium"
                            as={Link}
                            to={`/dash/projects/${project.id}`}
                          >
                            {t('projects.services')}
                          </Button>
                          <Button
                            variant="light"
                            size="sm"
                            className="rounded-pill px-3 me-2 text-primary fw-medium"
                            as={Link}
                            to={`/dash/data?project=${project.name}`}
                          >
                            {t('data.batches')}
                          </Button>
                          <Button
                            variant="outline-secondary"
                            size="sm"
                            className="rounded-pill px-2 me-2"
                            onClick={() => handleEditProject(project)}
                            title={t('common.edit')}
                          >
                            <FaEdit size={12} />
                          </Button>
                          <Button
                            variant="outline-danger"
                            size="sm"
                            className="rounded-pill px-2"
                            onClick={() => handleDeleteProject(project)}
                            title={t('common.delete')}
                          >
                            <FaTrash size={12} />
                          </Button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="4" className="text-center py-5 text-muted">
                        <div className="mb-3">
                          <FaPlus size={24} className="text-muted opacity-25" />
                        </div>
                        <p className="mb-0">{t('projects.noProjects')}</p>
                      </td>
                    </tr>
                  )}
                </tbody>
              </Table>
            </div>

            {paginatedProjects.length > 0 && (
              <div className="d-flex justify-content-between align-items-center mt-4">
                <span className="text-muted small">
                  {t('common.showing')} {(currentPage - 1) * pageSize + 1} -{" "}
                  {Math.min(currentPage * pageSize, projects.length)} {t('common.of')}{" "}
                  {projects.length}
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
      </div>

      {/* Modal for creating/editing a project */}
      <Modal show={showModal} onHide={() => { handleCloseModal(); setEditingProject(null); }} centered>
        <Modal.Body
          className="p-5"
          style={{ backgroundColor: "#f0f4ff", borderRadius: "15px" }}
        >
          <h4 className="mb-4 text-center">
            {editingProject ? t('projects.editProject') || 'Edit Project' : t('projects.createNew')}
          </h4>
          <Form>
            {submitSuccess && (
              <Alert variant="success" className="text-center">
                {editingProject ? t('projects.updateSuccess') || 'Project updated successfully!' : t('projects.createSuccess')}
              </Alert>
            )}
            {submitError && (
              <Alert variant="danger" className="text-center">
                {submitError}
              </Alert>
            )}

            <Form.Group className="mb-3">
              <Form.Label>{t('projects.name')}</Form.Label>
              <Form.Control
                type="text"
                name="name"
                placeholder={t('projects.namePlaceholder')}
                value={formData.name}
                onChange={handleChange}
                required
              />
            </Form.Group>

            <Form.Group className="mb-4">
              <Form.Label>{t('projects.description')}</Form.Label>
              <Form.Control
                as="textarea"
                name="description"
                placeholder={t('projects.descriptionPlaceholder')}
                value={formData.description}
                onChange={handleChange}
                rows={3}
                maxLength={500}
              />
              <div className="text-muted small text-end mt-1">
                {(formData.description || '').length}/500
              </div>
            </Form.Group>

            {/* Environment Selection */}
            <Form.Group className="mb-4">
              <div className="d-flex justify-content-between align-items-center mb-2">
                <Form.Label className="mb-0">{t('projects.environments') || 'Environments'}</Form.Label>
                <Button
                  variant="outline-primary"
                  size="sm"
                  onClick={handleAddCustomEnvironment}
                  className="py-0 px-2"
                >
                  + {t('projects.addEnvironment') || 'Add Environment'}
                </Button>
              </div>
              <p className="text-muted small mb-2">
                {t('projects.environmentsHelp') || 'Select environments for batch creation. Edit branch patterns to match your workflow.'}
              </p>
              <div className="border rounded" style={{ backgroundColor: '#fff' }}>
                {environments.map((env, index) => {
                  const isDefault = ['development', 'staging', 'production'].includes(env.name);
                  return (
                    <div
                      key={env.name}
                      className={`p-3 ${index < environments.length - 1 ? 'border-bottom' : ''}`}
                    >
                      <div className="d-flex align-items-start">
                        <Form.Check
                          type="checkbox"
                          id={`env-${env.name}`}
                          checked={env.is_active}
                          onChange={() => handleEnvironmentToggle(env.name)}
                          label=""
                          className="me-2 mt-1"
                        />
                        <div className="flex-grow-1">
                          <div className="d-flex justify-content-between align-items-center mb-1">
                            <span className="fw-medium">{env.display_name}</span>
                            {!isDefault && (
                              <Button
                                variant="link"
                                size="sm"
                                className="text-danger p-0"
                                onClick={() => handleRemoveEnvironment(env.name)}
                              >
                                ✕
                              </Button>
                            )}
                          </div>
                          <Form.Control
                            type="text"
                            size="sm"
                            value={env.branch_patterns.join(', ')}
                            onChange={(e) => handlePatternChange(env.name, e.target.value)}
                            placeholder="branch patterns (comma-separated)"
                            className="text-muted"
                            style={{ fontSize: '0.85rem' }}
                          />
                          <small className="text-muted">
                            {t('projects.patternHelp') || 'Comma-separated patterns (e.g., main, master, release/*)'}
                          </small>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Form.Group>

            <div className="d-flex justify-content-end">
              <Button
                variant="light"
                onClick={() => { handleCloseModal(); setEditingProject(null); }}
                className="me-2 rounded-pill px-4"
                disabled={isSubmitting}
              >
                {t('common.cancel')}
              </Button>
              <Button
                variant="primary"
                onClick={handleFormSubmit}
                className="rounded-pill px-4"
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <span
                      className="spinner-border spinner-border-sm me-2"
                      role="status"
                      aria-hidden="true"
                    ></span>
                    {editingProject ? t('projects.updating') || 'Updating...' : t('projects.creating')}
                  </>
                ) : (
                  editingProject ? t('projects.updateProject') || 'Update Project' : t('projects.createProject')
                )}
              </Button>
            </div>
          </Form>
        </Modal.Body>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={showDeleteModal} onHide={() => { setShowDeleteModal(false); setDeletingProject(null); }} centered>
        <Modal.Body className="p-4 text-center">
          <h5 className="mb-3">{t('projects.deleteConfirm') || 'Delete Project?'}</h5>
          <p className="text-muted mb-4">
            {t('projects.deleteWarning') || 'This will permanently delete the project and all its batches. This action cannot be undone.'}
          </p>
          <p className="fw-bold text-danger mb-4">
            {deletingProject?.name}
          </p>
          <div className="d-flex justify-content-center gap-2">
            <Button
              variant="light"
              onClick={() => { setShowDeleteModal(false); setDeletingProject(null); }}
              className="rounded-pill px-4"
              disabled={isDeleting}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="danger"
              onClick={handleConfirmDelete}
              className="rounded-pill px-4"
              disabled={isDeleting}
            >
              {isDeleting ? (
                <>
                  <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                  {t('common.deleting') || 'Deleting...'}
                </>
              ) : (
                t('common.delete') || 'Delete'
              )}
            </Button>
          </div>
        </Modal.Body>
      </Modal>
    </div>
  );
};

export default Project;
