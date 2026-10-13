import React, { useState } from "react";
import {
  Table,
  Pagination,
  Form,
  Button,
  Dropdown,
  Alert,
} from "react-bootstrap";
import { FaSearch, FaExclamationCircle } from "react-icons/fa";
import { useNavigate, useParams } from "react-router-dom";

const Errors = () => {
  const { batchId } = useParams();
  const [errors] = useState([
    {
      id: 1,
      timestamp: "2021-09-24 13:43:40.535 PDT",
      details: "[ERROR] [auth-service] Error 400",
    },
    {
      id: 2,
      timestamp: "2021-09-24 13:43:40.535 PDT",
      details:
        "[ERROR] [auth-service] Login request from User : user@email.com ipaddr:172.0.0.1",
    },
    {
      id: 3,
      timestamp: "2021-09-24 13:43:40.535 PDT",
      details: "[ERROR] [auth-service] User login failed : invalid password",
    },
    {
      id: 4,
      timestamp: "2021-09-24 13:43:40.535 PDT",
      details: "[ERROR] [auth-service] Login request from User : ERROR 400",
    },
    {
      id: 5,
      timestamp: "2021-09-24 13:43:40.535 PDT",
      details: "[ERROR] [auth-service] ERROR 500",
    },
  ]);

  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 6;
  const navigate = useNavigate();

  const [selectedTime, setSelectedTime] = useState("30 min");
  const [selectedService, setSelectedService] = useState("auth-service");
  const [selectedData, setSelectedData] = useState("Errors");
  const [selectedDeepseek, setSelectedDeepseek] = useState("Deepseek");
  const [selectedNewest, setSelectedNewest] = useState("Newest");
  const [showAlert, setShowAlert] = useState(false);

  const paginatedErrors = errors.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  const handleTimeChange = (time) => setSelectedTime(time);
  const handleServiceChange = (service) => setSelectedService(service);
  const handleDataChange = (data) => {
    setSelectedData(data);
    if (data === "Metrics") {
      navigate(`/dash/metrics/${batchId}`);
    } else if (data === "Errors") {
      navigate(`/dash/errors/${batchId}`);
    } else if (data === "Logs") {
      navigate(`/dash/data`);
    }
  };
  const handleDeepseekChange = (deepseek) => setSelectedDeepseek(deepseek);
  const handleNewestChange = (newest) => setSelectedNewest(newest);

  const handleSendToIA = () => {
    setShowAlert(true);
    setTimeout(() => setShowAlert(false), 3000);
  };

  return (
    <div
      className="p-3 d-flex justify-content-center"
      style={{ marginLeft: "22%", marginRight: "1%" }}
    >
      <div
        className="bg-white p-3 rounded-3"
        style={{ maxWidth: "1100px", width: "200%" }}
      >
        <div className="d-flex justify-content-between align-items-start mb-2">
          <div className="d-flex gap-1">
            <Form.Group className="position-relative">
              <Form.Control
                type="text"
                placeholder="Search"
                className="me-2 rounded-3 ps-5"
                style={{
                  width: "150px",
                  paddingLeft: "30px",
                  fontSize: "14px",
                }}
              />
              <FaSearch
                className="position-absolute"
                style={{
                  top: "50%",
                  left: "10px",
                  transform: "translateY(-85%)",
                  color: "#aaa",
                  fontSize: "14px",
                }}
              />
            </Form.Group>

            <Dropdown>
              <Dropdown.Toggle
                variant="light"
                className="rounded-3"
                style={{ fontSize: "14px" }}
              >
                Service: {selectedService}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() => handleServiceChange("auth-service")}
                  style={{ fontSize: "14px" }}
                >
                  auth-service
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleServiceChange("deploy-service")}
                  style={{ fontSize: "14px" }}
                >
                  deploy-service
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>

            <Dropdown>
              <Dropdown.Toggle
                variant="light"
                className="rounded-3"
                style={{ fontSize: "14px" }}
              >
                Data type: {selectedData}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() => handleDataChange("Logs")}
                  style={{ fontSize: "14px" }}
                >
                  Logs
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleDataChange("Metrics")}
                  style={{ fontSize: "14px" }}
                >
                  Metrics
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleDataChange("Errors")}
                  style={{ fontSize: "14px" }}
                >
                  Errors
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>

            <Dropdown>
              <Dropdown.Toggle
                variant="light"
                className="rounded-3"
                style={{ fontSize: "14px" }}
              >
                Time: {selectedTime}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() => handleTimeChange("30 min")}
                  style={{ fontSize: "14px" }}
                >
                  30 min
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleTimeChange("1 hour")}
                  style={{ fontSize: "14px" }}
                >
                  1 hour
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>

            <Dropdown>
              <Dropdown.Toggle
                variant="light"
                className="rounded-3"
                style={{ fontSize: "14px" }}
              >
                {selectedNewest}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() => handleNewestChange("Newest")}
                  style={{ fontSize: "14px" }}
                >
                  Newest
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleNewestChange("Oldest")}
                  style={{ fontSize: "14px" }}
                >
                  Oldest
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>

            <Dropdown>
              <Dropdown.Toggle
                variant="light"
                className="rounded-3"
                style={{ fontSize: "14px" }}
              >
                {selectedDeepseek}
              </Dropdown.Toggle>
              <Dropdown.Menu>
                <Dropdown.Item
                  onClick={() => handleDeepseekChange("Deepseek")}
                  style={{ fontSize: "14px" }}
                >
                  Deepseek
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleDeepseekChange("Chatgpt")}
                  style={{ fontSize: "14px" }}
                >
                  Chatgpt
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleDeepseekChange("Gemini")}
                  style={{ fontSize: "14px" }}
                >
                  Gemini
                </Dropdown.Item>
                <Dropdown.Item
                  onClick={() => handleDeepseekChange("Llama 3")}
                  style={{ fontSize: "14px" }}
                >
                  Llama 3
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>

            <Button
              variant="primary"
              className="d-flex align-items-center justify-content-center rounded-pill border-0 shadow"
              style={{
                width: "100px",
                height: "35px",
                backgroundColor: "#2B47D6",
                fontSize: "14px",
                fontWeight: "bold",
              }}
              onClick={handleSendToIA}
            >
              Send to IA
            </Button>
          </div>
        </div>

        {showAlert && (
          <Alert
            variant="info"
            onClose={() => setShowAlert(false)}
            dismissible
            style={{
              backgroundColor: "#73F3C2",
              color: "#000000",
              borderColor: "#73F3C2",
              fontSize: "14px",
            }}
          >
            Data sent to {selectedDeepseek} model.
          </Alert>
        )}

        <Table
          bordered
          hover
          responsive
          className="rounded-4 overflow-hidden text-center"
        >
          <thead className="table-primary">
            <tr>
              <th style={{ fontSize: "14px" }}>Select</th>
              <th style={{ fontSize: "14px" }}>Timestamp</th>
              <th style={{ fontSize: "14px" }}>Error Details</th>
            </tr>
          </thead>
          <tbody>
            {paginatedErrors.map((error) => (
              <tr key={error.id}>
                <td style={{ padding: "0.75rem", fontSize: "14px" }}>
                  <Form.Check type="checkbox" defaultChecked />
                </td>
                <td style={{ padding: "0.75rem", fontSize: "14px" }}>
                  {error.timestamp}
                </td>
                <td
                  style={{ padding: "0.75rem", fontSize: "14px" }}
                  className="d-flex align-items-center gap-2"
                >
                  <FaExclamationCircle className="text-danger" />{" "}
                  {error.details}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>

        <div className="d-flex justify-content-between align-items-center mt-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate("/dash/data")}
            style={{
              fontSize: "14px",
              backgroundColor: "#2B47D6",
              borderColor: "#2B47D6",
            }}
          >
            Back to Data
          </Button>

          <Pagination>
            <Pagination.Prev
              onClick={() => setCurrentPage(currentPage - 1)}
              disabled={currentPage === 1}
              style={{ fontSize: "14px" }}
            />
            <Pagination.Item
              active={currentPage === 1}
              onClick={() => setCurrentPage(1)}
              style={{ fontSize: "14px" }}
            >
              1
            </Pagination.Item>
            <Pagination.Item
              active={currentPage === 2}
              onClick={() => setCurrentPage(2)}
              style={{ fontSize: "14px" }}
            >
              2
            </Pagination.Item>
            <Pagination.Item
              active={currentPage === 3}
              onClick={() => setCurrentPage(3)}
              style={{ fontSize: "14px" }}
            >
              3
            </Pagination.Item>
            <Pagination.Ellipsis />
            <Pagination.Item
              onClick={() => setCurrentPage(40)}
              style={{ fontSize: "14px" }}
            >
              40
            </Pagination.Item>
            <Pagination.Next
              onClick={() => setCurrentPage(currentPage + 1)}
              disabled={currentPage === 40}
              style={{ fontSize: "14px" }}
            />
          </Pagination>
        </div>
      </div>
    </div>
  );
};

export default Errors;
