import React, { useState, useEffect } from "react";
import {
  Table,
  Form,
  InputGroup,
  Pagination,
  Dropdown,
  Button,
  Modal,
  Tabs,
  Tab,
} from "react-bootstrap";
import { FaTrash, FaEdit, FaPlus } from "react-icons/fa";
import { BsThreeDotsVertical } from "react-icons/bs";
import { OrganisationService } from "../services/organisation.service";
import DataService from "../services/data.service";
import { toast } from "react-toastify";
import TeamManagement from "./TeamManagement";
import SettingsIntegrations from "./SettingsIntegrations";

const SettingsOrg = () => {
  const [selectedTab, setSelectedTab] = useState("orgs");
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({ id: "", name: "", website: "" });
  const [organisations, setOrganisations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalPages, setTotalPages] = useState(1);
  const [deleteDays, setDeleteDays] = useState(2);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (selectedTab === "orgs") {
      fetchOrganisations();
    }

  }, [currentPage, selectedTab]);

  const fetchOrganisations = async () => {
    try {
      setLoading(true);
      const data = await OrganisationService.getAllOrganisations();
      setOrganisations(data);
      setTotalPages(Math.ceil(data.length / 10)); // Assuming 10 items per page
      setLoading(false);
    } catch (error) {
      toast.error("Erreur lors du chargement des organisations");
      setLoading(false);
    }
  };

  const handleOrgSelect = (orgId) => {
    const orgToEdit = organisations.find((org) => org.id === orgId);
    setFormData({
      id: orgToEdit.id,
      name: orgToEdit.name,
      website: orgToEdit.website || "",
    });
    setIsEditing(true);
    setShowModal(true);
  };

  const handleAddOrg = () => {
    setFormData({ id: "", name: "", website: "" });
    setIsEditing(false);
    setShowModal(true);
  };

  const handleRemoveOrg = async (orgId) => {
    try {
      await OrganisationService.deleteOrganisation(orgId);
      toast.success("Organisation supprimée avec succès");
      fetchOrganisations();
    } catch (error) {
      toast.error("Erreur lors de la suppression");
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      if (isEditing) {
        await OrganisationService.updateOrganisation(formData.id, formData);
        toast.success("Organisation mise à jour avec succès");
      } else {
        await OrganisationService.createOrganisation(formData);
        toast.success("Organisation créée avec succès");
      }
      setShowModal(false);
      fetchOrganisations();
    } catch (error) {
      toast.error(
        `Erreur: ${error.response?.data?.error || "Une erreur est survenue"}`
      );
    }
  };

  const handleDeleteBatches = async () => {
    if (
      !window.confirm(
        `Supprimer tous les batches de plus de ${deleteDays} jour(s) ?`
      )
    )
      return;
    setDeleting(true);
    try {
      const result = await DataService.deleteOldBatches(deleteDays);
      toast.success(result.message || "Batches supprimés !");
    } catch (error) {
      toast.error(
        error.response?.data?.error ||
        "Erreur lors de la suppression des batches"
      );
    }
    setDeleting(false);
  };

  const filteredOrganisations = organisations.filter(
    (org) =>
      org.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (org.website &&
        org.website.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  if (loading && selectedTab === "orgs") {
    return (
      <div
        className="p-4"
        style={{
          backgroundColor: "#e6ebff",
          minHeight: "100vh",
          marginTop: "6vh",
        }}
      >
        <div
          className="container bg-white rounded p-4 shadow"
          style={{ marginLeft: "400px" }}
        >
          <div className="d-flex justify-content-center">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="p-4"
      style={{
        backgroundColor: "#e6ebff",
        minHeight: "100vh",
        marginTop: "6vh",
        // Remove horizontal overflow
        overflowX: "hidden",
      }}
    >
      <div
        className="container bg-white rounded p-4 shadow"
        style={{
          // Remove marginLeft, set maxWidth and center
          maxWidth: "900px",
          margin: "0 auto",
          width: "100%",
        }}
      >
        <Tabs
          activeKey={selectedTab}
          onSelect={(k) => setSelectedTab(k)}
          className="mb-4"
        >
          <Tab eventKey="orgs" title="Gestion Organisation">
            <div className="d-flex justify-content-between align-items-center mb-4">
              <h4 className="text-primary mb-0">Gestion Organisation</h4>
              <Button
                variant="primary"
                onClick={handleAddOrg}
                style={{ borderRadius: "20px", padding: "0.5rem 1.5rem" }}
              >
                <FaPlus className="me-2" />
                Ajouter
              </Button>
            </div>

            {/* Search */}
            <div className="mb-4 d-flex justify-content-center">
              <InputGroup
                style={{
                  maxWidth: "400px",
                  boxShadow: "0px 4px 12px rgba(0,0,0,0.1)",
                }}
              >
                <InputGroup.Text className="bg-white border-end-0">
                  <i className="bi bi-search"></i>
                </InputGroup.Text>
                <Form.Control
                  placeholder="Rechercher des organisations..."
                  className="border-start-0"
                  style={{ backgroundColor: "white" }}
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              </InputGroup>
            </div>

            {/* Table */}
            <Table hover responsive="md" className="text-center">
              <thead>
                <tr className="text-primary">
                  <th>Nom</th>
                  <th>Website</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrganisations.length > 0 ? (
                  filteredOrganisations.map((org) => (
                    <tr key={org.id}>
                      <td>{org.name}</td>
                      <td>
                        {org.website ? (
                          <a
                            href={`https://${org.website}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {org.website}
                          </a>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>
                        <div className="d-flex align-items-center justify-content-center gap-2">
                          <Dropdown align="end">
                            <Dropdown.Toggle
                              as="div"
                              style={{ cursor: "pointer" }}
                            >
                              <BsThreeDotsVertical size={20} />
                            </Dropdown.Toggle>

                            <Dropdown.Menu>
                              <Dropdown.Item
                                onClick={() => handleOrgSelect(org.id)}
                              >
                                <FaEdit className="me-2 text-primary" />{" "}
                                Modifier
                              </Dropdown.Item>
                              <Dropdown.Item
                                onClick={() => handleRemoveOrg(org.id)}
                              >
                                <FaTrash className="me-2 text-danger" />{" "}
                                Supprimer
                              </Dropdown.Item>
                            </Dropdown.Menu>
                          </Dropdown>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="3" className="text-muted py-4">
                      Aucune organisation trouvée
                    </td>
                  </tr>
                )}
              </tbody>
            </Table>

            {/* Pagination */}
            {filteredOrganisations.length > 0 && (
              <div className="d-flex justify-content-end mt-4">
                <Pagination className="mb-0">
                  <Pagination.Prev
                    onClick={() =>
                      setCurrentPage((prev) => Math.max(prev - 1, 1))
                    }
                    disabled={currentPage === 1}
                    style={{ fontSize: "14px" }}
                  />
                  {[...Array(totalPages).keys()].map((number) => (
                    <Pagination.Item
                      key={number + 1}
                      active={currentPage === number + 1}
                      onClick={() => setCurrentPage(number + 1)}
                      style={{ fontSize: "14px" }}
                    >
                      {number + 1}
                    </Pagination.Item>
                  ))}
                  <Pagination.Next
                    onClick={() =>
                      setCurrentPage((prev) => Math.min(prev + 1, totalPages))
                    }
                    disabled={currentPage === totalPages}
                    style={{ fontSize: "14px" }}
                  />
                </Pagination>
              </div>
            )}

            {/* Add/Edit Modal */}
            <Modal show={showModal} onHide={() => setShowModal(false)} centered>
              <Modal.Header closeButton>
                <Modal.Title>
                  {isEditing ? "Modifier Organisation" : "Ajouter Organisation"}
                </Modal.Title>
              </Modal.Header>
              <Modal.Body>
                <Form onSubmit={handleSubmit}>
                  <Form.Group className="mb-3">
                    <Form.Label>Nom</Form.Label>
                    <Form.Control
                      type="text"
                      name="name"
                      value={formData.name}
                      onChange={handleInputChange}
                      required
                    />
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>Website</Form.Label>
                    <Form.Control
                      type="text"
                      name="website"
                      value={formData.website}
                      onChange={handleInputChange}
                      placeholder="exemple.com (sans https://)"
                    />
                  </Form.Group>
                  <div className="d-flex justify-content-end gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => setShowModal(false)}
                    >
                      Annuler
                    </Button>
                    <Button variant="primary" type="submit">
                      {isEditing ? "Enregistrer" : "Ajouter"}
                    </Button>
                  </div>
                </Form>
              </Modal.Body>
            </Modal>
          </Tab>
          <Tab eventKey="delete" title="Data Retention">
            <div className="mb-4">
              <h4 className="text-primary mb-3">Batch Cleanup Policy</h4>
              <div className="d-flex align-items-center gap-2">
                <Form.Label className="mb-0">
                  Delete batches older than
                </Form.Label>
                <Form.Select
                  style={{ width: 80 }}
                  value={deleteDays}
                  onChange={(e) => setDeleteDays(Number(e.target.value))}
                  disabled={deleting}
                >
                  {[...Array(30).keys()].map((i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1} day{i + 1 > 1 ? "s" : ""}
                    </option>
                  ))}
                </Form.Select>
                <Button
                  variant="danger"
                  onClick={handleDeleteBatches}
                  disabled={deleting}
                >
                  {deleting ? "Deleting..." : "Delete Batches"}
                </Button>
              </div>
            </div>
          </Tab>
          <Tab eventKey="integrations" title="Integrations">
            <SettingsIntegrations />
          </Tab>
          <Tab eventKey="team" title="Team Members">
            <TeamManagement embedded={true} />
          </Tab>
        </Tabs>
      </div>
    </div>
  );
};

export default SettingsOrg;
