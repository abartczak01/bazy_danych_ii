from flask import Flask, jsonify, request
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os #provides ways to access the Operating System and allows us to read the environment variables

load_dotenv()

app = Flask(__name__)
uri = os.getenv('URI')
user = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
driver = GraphDatabase.driver(uri, auth=(user, password),database="neo4j")

def get_employees(tx, filters=None, sort_by=None):
    query = "MATCH (e:Employee)"
    
    if filters:
        for key, value in filters.items():
            query += f" WHERE e.{key} = '{value}'"
    
    query += "RETURN e"

    if sort_by:
        query += f" ORDER BY e.{sort_by}"
    
    results = tx.run(query).data()
    employees = [{'name': result['e']['name'], 
                  'surname': result['e']['surname'], 
                  'position': result['e']['position'],
                  'department': result['e']['department']} 
                  for result in results]
    return employees


@app.route('/employees', methods=['GET'])
def get_employees_route():
    filters = {}
    sort_by = request.args.get('sort_by')

    filter_params = ['name', 'surname', 'department', 'position']

    for param in filter_params:
        if param in request.args:
            filters[param] = request.args.get(param)

    with driver.session() as session:
        employees = session.read_transaction(get_employees, filters=filters, sort_by=sort_by)

    response = {'employees': employees}
    return jsonify(response)


def is_employee_unique(tx, name, surname):
    query = f"MATCH (e:Employee {{name: '{name}', surname: '{surname}'}}) RETURN COUNT(e) as count"
    result = tx.run(query).single()
    return result["count"] == 0


def degrade_prev_manager(tx, department):
    query = f"MATCH (e:Employee {{department: '{department}', position: 'Manager'}})-[rel: MANAGES]->(d: Department) SET e.position = 'Employee' DELETE rel"
    tx.run(query, department=department)


def add_employee(tx, name, surname, position, department):
    query = f"MATCH (d: Department {{name: '{department}'}}) "
    query += f"CREATE (e:Employee {{name: '{name}', surname: '{surname}', position: '{position}', department: '{department}'}}) "
    query += f"CREATE (e)-[:WORKS_IN]->(d)"

    if position == "Manager":
        degrade_prev_manager(tx, department)
        query += f"CREATE (e)-[:MANAGES]->(d)"

    tx.run(query, name=name, surname=surname, position=position, department=department)


@app.route('/employees', methods=['POST'])
def add_employee_route():
    data = request.get_json()

    required_fields = ['name', 'surname', 'position', 'department']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    name = data['name']
    surname = data['surname']
    position = data['position']
    department = data['department']

    with driver.session() as session:
        if not session.read_transaction(is_employee_unique, name, surname):
            return jsonify({'error': 'Employee with the same name and surname already exists'}), 400
        if position == "Manager":
            session.write_transaction(degrade_prev_manager, department)
        session.write_transaction(add_employee, name, surname, position, department)

    return jsonify({'message': 'Employee added successfully'}), 201

def exists_employee(tx, employee_id):
    query = f"MATCH (e:Employee) WHERE ID(e) = {employee_id} RETURN COUNT(e) as count"
    result = tx.run(query).single()
    if result["count"] == 0:
        return False
    return True

def is_a_manager(tx, employee_id):
    query = f"MATCH (e:Employee)-[:MANAGES]->(d:Department) WHERE ID(e) = {employee_id} RETURN COUNT(e) as count"
    result = tx.run(query).single()
    if result["count"] == 0:
        return False
    return True


@app.route('/employees/<int:id>', methods=['DELETE'])
def delete_employee_route(id):
    with driver.session() as session:
        result = session.write_transaction(delete_employee, id)
        print(result)
    if result == "not_found":
        return jsonify({'error': 'Employee not found'}), 404
    else:
        return jsonify({'message': result}), 200

def delete_employee(tx, employee_id):
    if not exists_employee(tx, employee_id):
        return "not_found"
    
    if is_a_manager(tx, employee_id):
        delete_query = f"MATCH (m:Employee)-[:WORKS_IN]->(d:Department) WHERE ID(m) = {employee_id} DETACH DELETE m RETURN d.name"
        result = tx.run(delete_query).single()
        dep_name = result['d.name']
        mesg = handle_manager_deletion(tx, dep_name)
        return mesg
    
    else:
        delete_query = f"MATCH (e:Employee) WHERE ID(e) = {employee_id} DETACH DELETE e"
        tx.run(delete_query)
        return "deleted employee successfully"

def handle_manager_deletion(tx, dep_name):
    query_number_of_employees = f"MATCH (e:Employee)-[:WORKS_IN]->(d:Department {{name: '{dep_name}'}}) RETURN COUNT(e) AS number_of_employees"
    result = tx.run(query_number_of_employees).single()

    if result["number_of_employees"] >= 1:
        query_new_manager = f"MATCH (e:Employee)-[:WORKS_IN]->(d:Department {{name: '{dep_name}'}}) WITH e, d LIMIT 1 SET e.position = 'Manager' CREATE (e)-[:MANAGES]->(d) RETURN e"
        tx.run(query_new_manager)
        return "set new manager"
    else:
        query_delete_dep = f"MATCH (d: Department {{name: '{dep_name}'}}) DELETE d"
        tx.run(query_delete_dep)
        return "deleted department"


def edit_employee(tx, employee_id, data):
    # Pobierz aktualne dane pracownika
    current_data_query = f"MATCH (e:Employee) WHERE ID(e) = {employee_id} RETURN e"
    current_data = tx.run(current_data_query).single()

    if not current_data:
        return "Employee not found"

    # Przygotuj zapytanie edycji pracownika
    edit_query = "MATCH (e:Employee) WHERE ID(e) = $employee_id SET "
    parameters = {}

    # Sprawdź, czy dane są dostarczone, a następnie dodaj do zapytania edycji
    if 'name' in data:
        edit_query += "e.name = $name, "
        parameters['name'] = data['name']

    if 'surname' in data:
        edit_query += "e.surname = $surname, "
        parameters['surname'] = data['surname']

    if 'position' in data:
        edit_query += "e.position = $position, "
        parameters['position'] = data['position']

    if 'department' in data:
        # Sprawdź, czy departament istnieje
        # if not exists_department(tx, data['department_id']):
        #     return "Department not found"

        edit_query += "WITH e MATCH (d:Department) WHERE ID(d) = $department MERGE (e)-[:WORKS_IN]->(d) "
        parameters['department_id'] = data['department']

    # Usuń ostatnią spację i przecinek z zapytania
    edit_query = edit_query.rstrip(', ')

    # Uruchom zapytanie edycji pracownika
    tx.run(edit_query, employee_id=employee_id, **parameters)

    return "success"



@app.route('/employees/<int:id>', methods=['PUT'])
def edit_employee_route(id):
    with driver.session() as session:
        if not session.read_transaction(exists_employee, id):
            return jsonify({'error': 'employee not found'}), 404
    
        data = request.get_json()

        if not data:
            return jsonify({'error': 'no data provided for update'}), 400
        
        result = session.write_transaction(edit_employee, id, data)
        
        if result == "success":
            return jsonify({'message': 'Employee updated successfully'}), 200
        else:
            return jsonify({'error': result}), 500       


def get_subordinates(tx, id):
    if exists_employee(tx, id) and is_a_manager(tx, id):
        query = f"MATCH (m:Employee)-[:MANAGES]->(d:Department) WHERE ID(m) = {id} MATCH (e:Employee)-[:WORKS_IN]->(d) WHERE e.position <> 'Manager' RETURN e;"
        results = tx.run(query).data()
        subordinates = [{'name': result['e']['name'], 
                     'surname': result['e']['surname'], 
                     'position': result['e']['position'],
                     'department': result['e']['department']} 
                    for result in results]
        return subordinates
    return None


@app.route('/employees/<int:id>/subordinates', methods=['GET'])
def get_subordinates_route(id):
    with driver.session() as session:
        subordinates = session.read_transaction(get_subordinates, id)

        if subordinates is None:
            return jsonify({'error': 'Employee not found'}), 404

    response = {'subordinates': subordinates}
    return jsonify(response)


def get_department_info(tx, employee_id=None):
    query_dep_name = f"MATCH (e: Employee)-[:WORKS_IN]->(d: Department) WHERE ID(e) = {employee_id} RETURN d.name as name"
    dep_name = tx.run(query_dep_name).single()['name']

    query_employees_number = f"MATCH (e: Employee)-[]->(d: Department) WHERE d.name = '{dep_name}' RETURN COUNT(e) as numberOfEmployees"
    employees_number = tx.run(query_employees_number).single()["numberOfEmployees"]

    query_manager = f"MATCH (m: Employee)-[:MANAGES]->(d: Department) WHERE d.name = '{dep_name}' RETURN m"
    manager = tx.run(query_manager).data()[0]['m']

    info = {'name': dep_name, 'numberOfEmployees': employees_number, 'manager': manager}
    return info


@app.route('/employees/<int:id>/department', methods=['GET'])
def get_employees_department_info_route(id):
    with driver.session() as session:
        employee = session.read_transaction(exists_employee, id)
        
        if employee is None:
            return jsonify({'error': 'Employee not found'}), 404
        else:
            response = session.read_transaction(get_department_info, employee_id=id)
            return jsonify({'info': response}), 200



def get_all_departments(tx, filters=None, sort_by=None):
    query = "MATCH (e:Employee)-[:WORKS_IN]->(d:Department)"
    
    if filters:
        for key, value in filters.items():
            query += f" WHERE d.{key} = '{value}'"
    
    query += "RETURN d.name as name, COUNT(e) AS numberOfEmployees"

    if sort_by:
        query += f" ORDER BY {sort_by}"
    
    results = tx.run(query).data()
    return results


@app.route('/departments', methods=['GET'])
def get_all_departments_route():
    filters = {}
    sort_by = request.args.get('sort_by')

    filter_params = ['name', 'numberOfEmployees']

    if sort_by and sort_by not in filter_params:
        return jsonify({'error': 'you can only sort by name or by numberOfEmployees'}), 404

    for param in filter_params:
        if param in request.args:
            filters[param] = request.args.get(param)

    with driver.session() as session:
        print(filters, sort_by)
        departments = session.read_transaction(get_all_departments, filters=filters, sort_by=sort_by)

    return jsonify({'info': departments}), 200
        

@app.route('/departments/<int:department_id>/employees', methods=['GET'])
def get_department_employees_route(department_id):
    with driver.session() as session:
        result = session.run(f"MATCH (d:Department) WHERE ID(d) = {department_id} RETURN d", {"department_id": department_id})
        department_exists = result.data()
        print(department_exists)

        if not department_exists:
            return jsonify({"error": f"Department with ID {department_id} not found"}), 404

        result = session.run(f"MATCH (e:Employee)-[:WORKS_IN]->(d:Department) WHERE ID(d) = {department_id} RETURN e", {"department_id": department_id})
        employees = [{ "name": record["e"]["name"], "surname": record["e"]["surname"], "position": record["e"]["position"]} for record in result]
        return jsonify(employees)


if __name__ == '__main__':
    app.run()
